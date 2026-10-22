from __future__ import annotations

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


class ProviderGateway:
    """Session-gated dispatch for provider operations.

    Every operation is authorized against an active, owned, unexpired session
    before it reaches a provider. Provider instances are cached per session so
    stateful transports (e.g. an open serial connection) persist across calls.
    """

    _providers: dict[str, TargetProvider] = {}

    def __init__(
        self,
        session_repository: SessionRepository,
        audit_service: AuditService | None = None,
        target_repository: TargetRepository | None = None,
        agent_operation_service: AgentOperationService | None = None,
    ):
        self.session_repository = session_repository
        self.audit_service = audit_service
        self.target_repository = target_repository
        self.agent_operation_service = agent_operation_service

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
            provider = registry.build_provider(session.capability_type, provider_key, provider_config)
            self._providers[session.id] = provider
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

    def execute(
        self, session_id: str, user_id: str, operation: str, params: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        session = self._get_active_session(session_id, user_id)
        try:
            if self._uses_agent_transport(session):
                if operation not in AgentOperationService.operations_for_family(session.capability_type):
                    raise ConflictResource(
                        f"Operation '{operation}' is not supported by capability '{session.capability_type}'"
                    )
                if self.agent_operation_service is None:
                    raise ConflictResource("Agent transport is not configured")
                remote_result = self.agent_operation_service.execute_for_session(
                    session=session,
                    user_id=user_id,
                    operation=operation,
                    params=params or {},
                )
                result_message = remote_result.get("message", "ok")
                result_data = remote_result.get("data")
                result_success = True
            else:
                provider = self._get_provider(session)
                if operation not in provider.operations():
                    raise ConflictResource(
                        f"Operation '{operation}' is not supported by capability '{session.capability_type}'"
                    )
                result = provider.execute(operation, params or {})
                result_message = result.message
                result_data = result.data
                result_success = result.success
        except ConflictResource as exc:
            metrics.inc(
                "targethub_provider_operations_total",
                labels={
                    "capability": session.capability_type,
                    "operation": operation,
                    "success": "false",
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
                    success=False,
                    detail=str(exc),
                )
            raise

        metrics.inc(
            "targethub_provider_operations_total",
            labels={
                "capability": session.capability_type,
                "operation": operation,
                "success": str(result_success).lower(),
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
                success=result_success,
                detail=result_message,
            )

        if not result_success:
            raise ConflictResource(result_message)

        return {
            "session_id": session.id,
            "capability_type": session.capability_type,
            "provider_key": session.provider_key,
            "operation": operation,
            "message": result_message,
            "data": self._normalize(result_data),
        }

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
