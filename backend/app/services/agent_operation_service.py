from __future__ import annotations

import os
import time
from datetime import UTC, datetime, timedelta
from typing import Any

from app.core.exceptions import ConflictResource, ResourceNotFound
from app.models.agent_operation import AgentOperation
from app.repositories.agent_operation_repository import AgentOperationRepository
from app.repositories.agent_repository import AgentRepository
from app.repositories.session_repository import SessionRepository

SERIAL_OPERATION_ALLOWLIST = ("open", "read", "write", "close")
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
        if not session.agent_id or not session.resource_id:
            raise ConflictResource("Serial session is missing Agent/resource binding")

        normalized_operation = operation.strip().lower()
        if normalized_operation not in SERIAL_OPERATION_ALLOWLIST:
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
                params=self._sanitize_serial_params(normalized_operation, params or {}),
                status="pending",
                requested_by=user_id,
            )
        )
        return self._await_result(queued.id)

    def poll_for_agent(
        self,
        *,
        agent_id: str,
        wait_seconds: int,
        lease_seconds: int,
    ) -> AgentOperation | None:
        deadline = time.monotonic() + max(0, wait_seconds)
        lease_delta = timedelta(seconds=max(5, lease_seconds))
        while True:
            now = datetime.now(UTC)
            operation = self.operation_repository.claim_next(
                agent_id=agent_id,
                now=now,
                lease_expires_at=now + lease_delta,
                allowed_operations=list(SERIAL_OPERATION_ALLOWLIST),
            )
            if operation is not None:
                if self._is_operation_session_valid(operation, now):
                    return operation
                self._cancel_operation(operation, "Session is no longer active for this operation")

            if time.monotonic() >= deadline:
                return None
            time.sleep(self.poll_interval_seconds)

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
        return self.operation_repository.save(operation)

    @staticmethod
    def _sanitize_serial_params(operation: str, params: dict[str, Any]) -> dict[str, Any]:
        if operation in {"open", "close"}:
            return {}
        if operation == "read":
            size = int(params.get("size", 4096))
            if size < 1 or size > 65536:
                raise ConflictResource("Serial read size must be between 1 and 65536")
            return {"size": size}
        if operation == "write":
            text = params.get("text", "")
            if not isinstance(text, str):
                raise ConflictResource("Serial write text must be a string")
            if len(text) > 65536:
                raise ConflictResource("Serial write payload exceeds 65536 characters")
            return {"text": text}
        raise ConflictResource(f"Unsupported serial operation '{operation}'")

    def _await_result(self, operation_id: str) -> dict[str, Any]:
        deadline = time.monotonic() + self.operation_timeout_seconds
        while time.monotonic() < deadline:
            operation = self.operation_repository.get(operation_id)
            if operation is None:
                raise ResourceNotFound("Agent operation", operation_id)
            if operation.status == "completed":
                return {
                    "message": operation.detail or "ok",
                    "data": operation.result_data or {},
                }
            if operation.status in {"failed", "cancelled", "timed_out"}:
                raise ConflictResource(operation.detail or "Agent operation failed")
            time.sleep(self.poll_interval_seconds)

        operation = self.operation_repository.get(operation_id)
        if operation is not None and operation.status in {"pending", "in_progress"}:
            operation.status = "timed_out"
            operation.detail = "Agent did not complete the operation in time"
            operation.completed_at = datetime.now(UTC)
            operation.lease_expires_at = None
            self.operation_repository.save(operation)
        raise ConflictResource(
            "Agent did not complete serial operation in time; Agent may be offline or disconnected"
        )

    def _is_operation_session_valid(self, operation: AgentOperation, now: datetime) -> bool:
        session = self.session_repository.get(operation.session_id)
        if session is None:
            return False
        if session.status != "active":
            return False
        if _as_utc(session.expires_at) <= now:
            return False
        if session.capability_type != "serial":
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
