from __future__ import annotations

import os
import time
from datetime import UTC, datetime, timedelta
from typing import Any

from starlette.concurrency import run_in_threadpool

from app.core.exceptions import ConflictResource, ResourceNotFound
from app.models.agent_operation import AgentOperation
from app.providers import registry
from app.repositories.agent_operation_repository import AgentOperationRepository
from app.repositories.agent_repository import AgentRepository
from app.repositories.session_repository import SessionRepository
from app.services.operation_signals import (
    FALLBACK_INTERVAL_SECONDS,
    agent_key,
    operation_key,
    signals,
)

SERIAL_OPERATION_ALLOWLIST = ("open", "read", "write", "close")
POWER_OPERATION_ALLOWLIST = ("status", "on", "off", "reset", "cycle")
DEPLOY_OPERATION_ALLOWLIST = ("deploy", "status")
AGENT_OPERATION_ALLOWLISTS = {
    "serial": SERIAL_OPERATION_ALLOWLIST,
    "power": POWER_OPERATION_ALLOWLIST,
    "deploy": DEPLOY_OPERATION_ALLOWLIST,
}
ALL_AGENT_OPERATIONS = sorted({op for ops in AGENT_OPERATION_ALLOWLISTS.values() for op in ops})
# Long-running families get a larger wait/lease window than the serial default.
FAMILY_TIMEOUT_FLOOR_SECONDS = {"power": 30.0, "deploy": 600.0}
PENDING_EXPIRY_SECONDS = 900
TERMINAL_STATUSES = {"completed", "failed", "cancelled", "timed_out"}
# Serial reads may block on the Agent for up to this long waiting for data.
MAX_SERIAL_READ_WAIT_MS = 5000
SHA256_HEX_LENGTH = 64
DEFAULT_OPERATION_TIMEOUT_SECONDS = float(os.getenv("TARGETHUB_AGENT_OPERATION_TIMEOUT_SECONDS", "12"))
DEFAULT_POLL_INTERVAL_SECONDS = float(os.getenv("TARGETHUB_AGENT_OPERATION_POLL_INTERVAL_SECONDS", "0.1"))


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


class AgentOperationService:
    def __init__(
        self,
        operation_repository: AgentOperationRepository,
        session_repository: SessionRepository,
        agent_repository: AgentRepository,
        *,
        operation_timeout_seconds: float = DEFAULT_OPERATION_TIMEOUT_SECONDS,
        poll_interval_seconds: float = DEFAULT_POLL_INTERVAL_SECONDS,
    ):
        self.operation_repository = operation_repository
        self.session_repository = session_repository
        self.agent_repository = agent_repository
        self.operation_timeout_seconds = max(1.0, float(operation_timeout_seconds))
        self.poll_interval_seconds = max(0.05, float(poll_interval_seconds))

    @staticmethod
    def serial_operations() -> list[str]:
        return list(SERIAL_OPERATION_ALLOWLIST)

    @staticmethod
    def family_for(capability_type: str) -> str | None:
        family = registry.CAPABILITY_PROVIDERS.get(capability_type)
        return family if family in AGENT_OPERATION_ALLOWLISTS else None

    @classmethod
    def operations_for_family(cls, capability_type: str) -> list[str]:
        family = cls.family_for(capability_type)
        return list(AGENT_OPERATION_ALLOWLISTS[family]) if family else []

    @classmethod
    def uses_agent_transport(cls, session) -> bool:
        return (
            cls.family_for(session.capability_type) is not None
            and bool(session.agent_id)
            and bool(session.resource_id)
        )

    def timeout_for(self, capability_type: str) -> float:
        family = self.family_for(capability_type) or ""
        return max(self.operation_timeout_seconds, FAMILY_TIMEOUT_FLOOR_SECONDS.get(family, 0.0))

    def submit_for_session(
        self,
        *,
        session,
        user_id: str,
        operation: str,
        params: dict[str, Any] | None = None,
        detached: bool = False,
    ) -> AgentOperation:
        """Validate and queue an operation for the session's Agent; does not wait."""
        family = self.family_for(session.capability_type)
        if family is None:
            raise ConflictResource(
                f"Agent operation transport does not support '{session.capability_type}' sessions"
            )
        if not session.agent_id or not session.resource_id:
            raise ConflictResource("Session is missing Agent/resource binding")

        normalized_operation = operation.strip().lower()
        if normalized_operation not in AGENT_OPERATION_ALLOWLISTS[family]:
            raise ConflictResource(
                f"Operation '{operation}' is not supported by capability '{session.capability_type}'"
            )

        resource = self.agent_repository.get_resource(session.resource_id)
        if resource is None:
            raise ResourceNotFound("Agent resource", session.resource_id)
        if resource.agent_id != session.agent_id:
            raise ConflictResource("Session resource binding no longer matches the configured Agent")
        if not resource.available:
            raise ConflictResource("Configured Agent resource is unavailable")

        queued = self.operation_repository.create(
            AgentOperation(
                agent_id=session.agent_id,
                session_id=session.id,
                resource_id=session.resource_id,
                resource_key=resource.resource_key,
                resource_type=resource.resource_type,
                resource_metadata=resource.resource_metadata or {},
                operation=normalized_operation,
                params=self._sanitize_params(family, normalized_operation, params or {}),
                status="pending",
                requested_by=user_id,
                detached=detached,
            )
        )
        signals.notify(agent_key(session.agent_id))
        return queued

    def execute_for_session(
        self,
        *,
        session,
        user_id: str,
        operation: str,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Queue and synchronously wait (thread-blocking; prefer the async path in routes)."""
        queued = self.submit_for_session(
            session=session, user_id=user_id, operation=operation, params=params
        )
        family = self.family_for(session.capability_type) or "agent"
        return self._await_result(queued.id, self.timeout_for(session.capability_type), family)

    async def execute_for_session_async(
        self,
        *,
        session,
        user_id: str,
        operation: str,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        queued = await run_in_threadpool(
            lambda: self.submit_for_session(
                session=session, user_id=user_id, operation=operation, params=params
            )
        )
        family = self.family_for(session.capability_type) or "agent"
        return await self.await_result_async(
            queued.id, self.timeout_for(session.capability_type), family
        )

    def execute_serial(
        self,
        *,
        session,
        user_id: str,
        operation: str,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if session.capability_type != "serial":
            raise ConflictResource("Agent operation transport only supports serial sessions")
        return self.execute_for_session(
            session=session, user_id=user_id, operation=operation, params=params
        )

    def try_claim(self, *, agent_id: str, lease_seconds: int) -> AgentOperation | None:
        """Claim the next runnable operation for an Agent, if any (single attempt)."""
        lease_delta = timedelta(seconds=max(5, lease_seconds))
        while True:
            now = datetime.now(UTC)
            self.operation_repository.expire_stale(
                agent_id=agent_id,
                now=now,
                pending_before=now - timedelta(seconds=PENDING_EXPIRY_SECONDS),
            )
            operation = self.operation_repository.claim_next(
                agent_id=agent_id,
                now=now,
                lease_expires_at=now + lease_delta,
                allowed_operations=ALL_AGENT_OPERATIONS,
            )
            if operation is None:
                return None
            if self._is_operation_session_valid(operation, now):
                floor = FAMILY_TIMEOUT_FLOOR_SECONDS.get(self.family_for(operation.resource_type) or "", 0.0)
                if floor and (
                    operation.lease_expires_at is None
                    or _as_utc(operation.lease_expires_at) < now + timedelta(seconds=floor)
                ):
                    operation.lease_expires_at = now + timedelta(seconds=floor)
                    self.operation_repository.save(operation)
                return operation
            self._cancel_operation(operation, "Session is no longer active for this operation")

    def poll_for_agent(
        self,
        *,
        agent_id: str,
        wait_seconds: int,
        lease_seconds: int,
    ) -> AgentOperation | None:
        deadline = time.monotonic() + max(0, wait_seconds)
        while True:
            operation = self.try_claim(agent_id=agent_id, lease_seconds=lease_seconds)
            if operation is not None:
                return operation
            if time.monotonic() >= deadline:
                return None
            time.sleep(self.poll_interval_seconds)

    async def poll_for_agent_async(
        self,
        *,
        agent_id: str,
        wait_seconds: int,
        lease_seconds: int,
    ) -> AgentOperation | None:
        """Long-poll without holding a worker thread between database checks."""
        deadline = time.monotonic() + max(0, wait_seconds)
        async with signals.listen(agent_key(agent_id)) as listener:
            while True:
                operation = await run_in_threadpool(
                    lambda: self.try_claim(agent_id=agent_id, lease_seconds=lease_seconds)
                )
                if operation is not None:
                    return operation
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return None
                await listener.wait(min(FALLBACK_INTERVAL_SECONDS * 2, remaining))

    def complete_for_agent(
        self,
        *,
        agent_id: str,
        operation_id: str,
        success: bool,
        message: str,
        data: dict[str, Any] | None,
    ) -> AgentOperation:
        operation = self.operation_repository.get(operation_id)
        if operation is None:
            raise ResourceNotFound("Agent operation", operation_id)
        if operation.agent_id != agent_id:
            raise ConflictResource("Operation does not belong to this Agent")
        if operation.status not in {"pending", "in_progress"}:
            raise ConflictResource("Operation is already completed")

        operation.status = "completed" if success else "failed"
        operation.detail = message
        operation.result_data = data or {}
        operation.completed_at = datetime.now(UTC)
        operation.lease_expires_at = None
        saved = self.operation_repository.save(operation)
        signals.notify(operation_key(saved.id))
        return saved

    def get_for_session(self, session_id: str, operation_id: str) -> AgentOperation:
        operation = self.operation_repository.get(operation_id)
        if operation is None or operation.session_id != session_id:
            raise ResourceNotFound("Agent operation", operation_id)
        return operation

    @staticmethod
    def describe(operation: AgentOperation) -> dict[str, Any]:
        return {
            "operation_id": operation.id,
            "operation": operation.operation,
            "status": operation.status,
            "message": operation.detail,
            "data": operation.result_data or {},
            "requested_at": operation.requested_at,
            "completed_at": operation.completed_at,
        }

    @classmethod
    def _sanitize_params(cls, family: str, operation: str, params: dict[str, Any]) -> dict[str, Any]:
        if family == "serial":
            return cls._sanitize_serial_params(operation, params)
        if family == "deploy" and operation == "deploy":
            url = params.get("url")
            digest = params.get("sha256")
            if not isinstance(url, str) or not url.startswith(("https://", "http://")) or len(url) > 2048:
                raise ConflictResource("Deploy requires an http(s) artifact 'url'")
            if (
                not isinstance(digest, str)
                or len(digest) != SHA256_HEX_LENGTH
                or any(char not in "0123456789abcdefABCDEF" for char in digest)
            ):
                raise ConflictResource("Deploy requires a 64-character hex 'sha256'")
            return {"url": url, "sha256": digest.lower()}
        return {}

    @staticmethod
    def _sanitize_serial_params(operation: str, params: dict[str, Any]) -> dict[str, Any]:
        if operation in {"open", "close"}:
            return {}
        if operation == "read":
            try:
                size = int(params.get("size", 4096))
                wait_ms = int(params.get("wait_ms", 0))
            except (TypeError, ValueError) as exc:
                raise ConflictResource("Serial read size/wait_ms must be integers") from exc
            if size < 1 or size > 65536:
                raise ConflictResource("Serial read size must be between 1 and 65536")
            if wait_ms < 0 or wait_ms > MAX_SERIAL_READ_WAIT_MS:
                raise ConflictResource(
                    f"Serial read wait_ms must be between 0 and {MAX_SERIAL_READ_WAIT_MS}"
                )
            sanitized: dict[str, Any] = {"size": size}
            if wait_ms:
                sanitized["wait_ms"] = wait_ms
            return sanitized
        if operation == "write":
            text = params.get("text", "")
            if not isinstance(text, str):
                raise ConflictResource("Serial write text must be a string")
            if len(text) > 65536:
                raise ConflictResource("Serial write payload exceeds 65536 characters")
            return {"text": text}
        raise ConflictResource(f"Unsupported serial operation '{operation}'")

    @staticmethod
    def _outcome(operation: AgentOperation | None, operation_id: str) -> dict[str, Any] | None:
        """Return the result for a finished operation, raise on failure, None if still running."""
        if operation is None:
            raise ResourceNotFound("Agent operation", operation_id)
        if operation.status == "completed":
            return {"message": operation.detail or "ok", "data": operation.result_data or {}}
        if operation.status in {"failed", "cancelled", "timed_out"}:
            raise ConflictResource(operation.detail or "Agent operation failed")
        return None

    def _time_out(self, operation_id: str, family: str) -> None:
        operation = self.operation_repository.get(operation_id)
        if operation is not None and operation.status in {"pending", "in_progress"}:
            operation.status = "timed_out"
            operation.detail = "Agent did not complete the operation in time"
            operation.completed_at = datetime.now(UTC)
            operation.lease_expires_at = None
            self.operation_repository.save(operation)
        raise ConflictResource(
            f"Agent did not complete {family} operation in time; Agent may be offline or disconnected"
        )

    def _snapshot(self, operation_id: str):
        snapshot = getattr(self.operation_repository, "snapshot", None)
        return snapshot(operation_id) if snapshot else self.operation_repository.get(operation_id)

    def _await_result(self, operation_id: str, timeout: float, family: str) -> dict[str, Any]:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            outcome = self._outcome(self._snapshot(operation_id), operation_id)
            if outcome is not None:
                return outcome
            time.sleep(self.poll_interval_seconds)
        self._time_out(operation_id, family)
        raise AssertionError("unreachable")  # pragma: no cover

    async def await_result_async(self, operation_id: str, timeout: float, family: str) -> dict[str, Any]:
        deadline = time.monotonic() + timeout
        async with signals.listen(operation_key(operation_id)) as listener:
            while True:
                operation = await run_in_threadpool(self._snapshot, operation_id)
                outcome = self._outcome(operation, operation_id)
                if outcome is not None:
                    return outcome
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                await listener.wait(min(FALLBACK_INTERVAL_SECONDS, remaining))
        await run_in_threadpool(self._time_out, operation_id, family)
        raise AssertionError("unreachable")  # pragma: no cover

    def _is_operation_session_valid(self, operation: AgentOperation, now: datetime) -> bool:
        session = self.session_repository.get(operation.session_id)
        if session is None:
            return False
        if operation.operation == "close" and (operation.params or {}).get("cleanup"):
            # Releasing hardware for an ended session is always allowed.
            return session.agent_id == operation.agent_id and session.resource_id == operation.resource_id
        if session.status != "active":
            return False
        if _as_utc(session.expires_at) <= now:
            return False
        if self.family_for(session.capability_type) is None:
            return False
        if session.agent_id != operation.agent_id:
            return False
        if session.resource_id != operation.resource_id:
            return False
        return True

    def _cancel_operation(self, operation: AgentOperation, detail: str) -> AgentOperation:
        operation.status = "cancelled"
        operation.detail = detail
        operation.completed_at = datetime.now(UTC)
        operation.lease_expires_at = None
        return self.operation_repository.save(operation)
