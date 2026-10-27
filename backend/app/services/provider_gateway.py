from __future__ import annotations

import threading
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from app.core.exceptions import ConflictResource, ResourceNotFound
from app.core.metrics import metrics
from app.providers import registry
from app.providers.base import TargetProvider
from app.repositories.session_repository import SessionRepository
from app.repositories.target_repository import TargetRepository
from app.services.agent_operation_service import AgentOperationService
from app.services.audit_service import AuditService
from app.services.capability_binding import validate_capability_runtime_binding


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


MAX_CACHED_PROVIDERS = 256


class _ProviderCache:
    """Bounded, thread-safe LRU of stateful hub-side providers keyed by session id."""

    def __init__(self, capacity: int = MAX_CACHED_PROVIDERS) -> None:
        self.capacity = capacity
        self._lock = threading.Lock()
        self._items: OrderedDict[str, TargetProvider] = OrderedDict()

    def get(self, key: str) -> TargetProvider | None:
        with self._lock:
            provider = self._items.get(key)
            if provider is not None:
                self._items.move_to_end(key)
            return provider

    def put(self, key: str, provider: TargetProvider) -> None:
        with self._lock:
            self._items[key] = provider
            self._items.move_to_end(key)
            while len(self._items) > self.capacity:
                self._items.popitem(last=False)

    def pop(self, key: str, default=None):
        with self._lock:
            return self._items.pop(key, default)

    def __len__(self) -> int:
        with self._lock:
            return len(self._items)


@dataclass
class PendingOperation:
    """An Agent operation queued by ``ProviderGateway.begin`` and not yet finished."""

    session: Any
    operation: str
    operation_id: str
    timeout: float
    family: str
    params: dict[str, Any] | None = None

    def completed(self, remote: dict[str, Any]) -> CompletedOperation:
        return CompletedOperation(
            self.session,
            self.operation,
            remote.get("message", "ok"),
            remote.get("data"),
            params=self.params,
        )


@dataclass
class CompletedOperation:
    session: Any
    operation: str
    message: str
    data: dict[str, Any] | None = field(default=None)
    success: bool = True
    params: dict[str, Any] | None = field(default=None)


class ProviderGateway:
    """Session-gated dispatch for provider operations.

    Every operation is authorized against an active, owned, unexpired session
    before it reaches a provider. Provider instances are cached per session so
    stateful transports (e.g. an open serial connection) persist across calls.
    """

    _providers = _ProviderCache()

    def __init__(
        self,
        session_repository: SessionRepository,
        audit_service: AuditService | None = None,
        target_repository: TargetRepository | None = None,
        agent_operation_service: AgentOperationService | None = None,
        serial_log_repository=None,
    ):
        self.session_repository = session_repository
        self.audit_service = audit_service
        self.target_repository = target_repository
        self.agent_operation_service = agent_operation_service
        self.serial_log_repository = serial_log_repository

    @staticmethod
    def _uses_agent_transport(session) -> bool:
        """Serial always runs on the Agent; power/deploy opt in with provider_config transport=agent."""
        if not AgentOperationService.uses_agent_transport(session):
            return False
        if session.capability_type == "serial":
            return True
        provider_config = getattr(session, "_provider_config", None) or {}
        return provider_config.get("transport") == "agent"

    def _validate_runtime_binding(self, session):
        if self.target_repository is None:
            return None
        if not session.capability_id:
            raise ConflictResource("Session is missing capability binding information")

        target = self.target_repository.get(session.target_id)
        if target is None:
            raise ResourceNotFound("Target", session.target_id)

        capability = next(
            (item for item in target.capabilities if item.id == session.capability_id),
            None,
        )
        if capability is None or not capability.enabled:
            raise ConflictResource("Configured capability is unavailable")

        if capability.capability_type != session.capability_type:
            raise ConflictResource("Session capability no longer matches configured capability")
        if capability.provider_key != session.provider_key:
            raise ConflictResource("Session provider no longer matches configured capability")
        if capability.agent_id != session.agent_id or capability.resource_id != session.resource_id:
            raise ConflictResource("Session Agent/resource binding no longer matches configured capability")

        validate_capability_runtime_binding(capability)
        return capability

    def _get_active_session(self, session_id: str, user_id: str):
        now = datetime.now(UTC)
        self.session_repository.expire_due(now)

        session = self.session_repository.get(session_id)
        if session is None:
            raise ResourceNotFound("Session", session_id)
        if session.user_id != user_id:
            raise ConflictResource("Only the session owner can perform provider operations")
        if session.status != "active":
            raise ConflictResource(f"Session '{session_id}' is {session.status}")
        if _as_utc(session.expires_at) <= now:
            raise ConflictResource("Session has expired")
        if not registry.is_supported(session.capability_type):
            raise ConflictResource(
                f"Capability type '{session.capability_type}' has no provider"
            )
        capability = self._validate_runtime_binding(session)
        provider_config = {}
        if capability is not None:
            provider_config = capability.provider_config or {}
        setattr(session, "_provider_config", provider_config)
        return session

    def _get_provider(self, session) -> TargetProvider:
        provider = self._providers.get(session.id)
        if provider is None:
            provider_key = session.provider_key or f"{session.capability_type}:{session.target_id}"
            provider_config = getattr(session, "_provider_config", {})
            try:
                provider = registry.build_provider(session.capability_type, provider_key, provider_config)
            except ValueError as exc:
                raise ConflictResource(str(exc)) from exc
            self._providers.put(session.id, provider)
        return provider

    @staticmethod
    def _normalize(data: dict[str, Any] | None) -> dict[str, Any] | None:
        if not data or "data" not in data:
            return data
        payload = dict(data)
        raw = payload.get("data")
        if isinstance(raw, (bytes, bytearray)):
            payload["data_hex"] = bytes(raw).hex()
            payload["data_text"] = bytes(raw).decode("utf-8", errors="replace")
            payload["data"] = payload["data_text"]
        return payload

    def operations_for(self, session_id: str, user_id: str) -> dict[str, Any]:
        session = self._get_active_session(session_id, user_id)
        if self._uses_agent_transport(session):
            operations = AgentOperationService.operations_for_family(session.capability_type)
        else:
            provider = self._get_provider(session)
            operations = provider.operations()
        return {
            "session_id": session.id,
            "capability_type": session.capability_type,
            "provider_key": session.provider_key,
            "operations": operations,
        }

    def _record(self, session, user_id, operation, success, detail) -> None:
        metrics.inc(
            "targethub_provider_operations_total",
            labels={
                "capability": session.capability_type,
                "operation": operation,
                "success": str(success).lower(),
            },
        )
        if self.audit_service is not None:
            self.audit_service.record(
                action="provider.execute",
                user_id=user_id,
                target_id=session.target_id,
                session_id=session.id,
                provider_key=session.provider_key,
                capability_type=session.capability_type,
                operation=operation,
                success=success,
                detail=detail,
            )

    def _result(self, session, operation, message, data) -> dict[str, Any]:
        return {
            "session_id": session.id,
            "capability_type": session.capability_type,
            "provider_key": session.provider_key,
            "operation": operation,
            "message": message,
            "data": self._normalize(data),
        }

    def begin(
        self,
        session_id: str,
        user_id: str,
        operation: str,
        params: dict[str, Any] | None = None,
        *,
        detached: bool = False,
    ) -> PendingOperation | CompletedOperation:
        """Authorize and start an operation.

        Hub-side providers run to completion here. Agent-backed operations are
        queued and returned as ``PendingOperation`` for the caller to await.
        """
        session = self._get_active_session(session_id, user_id)
        try:
            if self._uses_agent_transport(session):
                if operation not in AgentOperationService.operations_for_family(session.capability_type):
                    raise ConflictResource(
                        f"Operation '{operation}' is not supported by capability '{session.capability_type}'"
                    )
                if self.agent_operation_service is None:
                    raise ConflictResource("Agent transport is not configured")
                queued = self.agent_operation_service.submit_for_session(
                    session=session,
                    user_id=user_id,
                    operation=operation,
                    params=params or {},
                    detached=detached,
                )
                return PendingOperation(
                    session=session,
                    operation=operation,
                    operation_id=queued.id,
                    timeout=self.agent_operation_service.timeout_for(session.capability_type),
                    family=AgentOperationService.family_for(session.capability_type) or "agent",
                    params=params or {},
                )
            provider = self._get_provider(session)
            if operation not in provider.operations():
                raise ConflictResource(
                    f"Operation '{operation}' is not supported by capability '{session.capability_type}'"
                )
            result = provider.execute(operation, params or {})
        except ConflictResource as exc:
            self._record(session, user_id, operation, False, str(exc))
            raise
        return CompletedOperation(
            session, operation, result.message, result.data, result.success, params=params or {}
        )

    def _capture(self, outcome: CompletedOperation, result: dict[str, Any]) -> None:
        """Append serial console traffic to the session transcript."""
        if self.serial_log_repository is None or outcome.session.capability_type != "serial":
            return
        try:
            if outcome.operation == "read":
                text = (result.get("data") or {}).get("data_text") or ""
                self.serial_log_repository.append(outcome.session.id, "out", text)
            elif outcome.operation == "write":
                text = str((outcome.params or {}).get("text", ""))
                self.serial_log_repository.append(outcome.session.id, "in", text)
        except Exception as exc:  # pragma: no cover - transcript is best effort
            from app.core.logging import logger

            logger.warning(f"Failed to store serial transcript: {exc}")

    def finish(self, user_id: str, outcome: CompletedOperation) -> dict[str, Any]:
        quiet = outcome.session.capability_type == "serial" and outcome.operation in {"read", "write"}
        if quiet:
            # Console reads/writes are high-volume; they go to the transcript and
            # metrics, not one audit row per keystroke.
            metrics.inc(
                "targethub_provider_operations_total",
                labels={
                    "capability": "serial",
                    "operation": outcome.operation,
                    "success": str(outcome.success).lower(),
                },
            )
        else:
            self._record(outcome.session, user_id, outcome.operation, outcome.success, outcome.message)
        if not outcome.success:
            raise ConflictResource(outcome.message)
        result = self._result(outcome.session, outcome.operation, outcome.message, outcome.data)
        self._capture(outcome, result)
        return result

    def fail(self, user_id: str, pending: PendingOperation, exc: Exception) -> None:
        self._record(pending.session, user_id, pending.operation, False, str(exc))

    def accepted(self, user_id: str, pending: PendingOperation) -> dict[str, Any]:
        """Response for a detached (asynchronous) submission."""
        self._record(pending.session, user_id, pending.operation, True, "queued")
        return {
            **self._result(pending.session, pending.operation, "Operation queued", None),
            "operation_id": pending.operation_id,
            "status": "pending",
        }

    def execute(
        self, session_id: str, user_id: str, operation: str, params: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Synchronous execute (blocks the calling thread for Agent operations)."""
        outcome = self.begin(session_id, user_id, operation, params)
        if isinstance(outcome, PendingOperation):
            try:
                remote = self.agent_operation_service._await_result(
                    outcome.operation_id, outcome.timeout, outcome.family
                )
            except ConflictResource as exc:
                self.fail(user_id, outcome, exc)
                raise
            outcome = outcome.completed(remote)
        return self.finish(user_id, outcome)

    async def execute_async(
        self,
        session_id: str,
        user_id: str,
        operation: str,
        params: dict[str, Any] | None = None,
        *,
        detached: bool = False,
    ) -> dict[str, Any]:
        """Route-friendly execute: database and provider work run in the threadpool,
        while waiting for an Agent result happens on the event loop."""
        from starlette.concurrency import run_in_threadpool

        outcome = await run_in_threadpool(
            lambda: self.begin(session_id, user_id, operation, params, detached=detached)
        )
        if isinstance(outcome, PendingOperation):
            if detached:
                return await run_in_threadpool(self.accepted, user_id, outcome)
            try:
                remote = await self.agent_operation_service.await_result_async(
                    outcome.operation_id, outcome.timeout, outcome.family
                )
            except ConflictResource as exc:
                await run_in_threadpool(self.fail, user_id, outcome, exc)
                raise
            outcome = outcome.completed(remote)
        return await run_in_threadpool(self.finish, user_id, outcome)

    def operation_status(self, session_id: str, user_id: str, operation_id: str, *, is_admin: bool):
        session = self.session_repository.get(session_id)
        if session is None:
            raise ResourceNotFound("Session", session_id)
        if session.user_id != user_id and not is_admin:
            raise ConflictResource("Only the session owner can view its operations")
        if self.agent_operation_service is None:
            raise ResourceNotFound("Agent operation", operation_id)
        operation = self.agent_operation_service.get_for_session(session_id, operation_id)
        described = AgentOperationService.describe(operation)
        described["data"] = self._normalize(described["data"])
        return described

    def release_session(self, session_id: str) -> None:
        """Drop any cached provider for a closed/expired session."""
        self._providers.pop(session_id, None)

    # Backward-compatible serial helpers used by existing endpoints/UI.
    def serial_open(self, session_id: str, user_id: str):
        return self.execute(session_id, user_id, "open")

    def serial_read(self, session_id: str, user_id: str, size: int = 4096):
        # Ensure the transport is open, then read (idempotent open).
        self.execute(session_id, user_id, "open")
        return self.execute(session_id, user_id, "read", {"size": size})

    def serial_write(self, session_id: str, user_id: str, text: str):
        self.execute(session_id, user_id, "open")
        return self.execute(session_id, user_id, "write", {"text": text})

    def serial_close(self, session_id: str, user_id: str):
        return self.execute(session_id, user_id, "close")
