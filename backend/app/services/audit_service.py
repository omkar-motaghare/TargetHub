from __future__ import annotations

from app.core.logging import logger
from app.models.audit import AuditLog
from app.repositories.audit_repository import AuditRepository


class AuditService:
    """Records and queries audit events.

    Recording is best-effort: an audit failure must never block the primary
    operation, so ``record`` swallows and logs persistence errors.
    """

    def __init__(self, repository: AuditRepository):
        self.repository = repository

    def record(
        self,
        action: str,
        user_id: str | None = None,
        target_id: str | None = None,
        session_id: str | None = None,
        provider_key: str | None = None,
        capability_type: str | None = None,
        operation: str | None = None,
        success: bool = True,
        detail: str | None = None,
    ) -> None:
        try:
            self.repository.create(
                AuditLog(
                    action=action,
                    user_id=user_id,
                    target_id=target_id,
                    session_id=session_id,
                    provider_key=provider_key,
                    capability_type=capability_type,
                    operation=operation,
                    success=success,
                    detail=detail,
                )
            )
        except Exception as exc:  # pragma: no cover - defensive best-effort audit
            logger.warning(f"Failed to record audit event '{action}': {exc}")

    def list(self, user_id=None, target_id=None, session_id=None, limit=200):
        return self.repository.list(
            user_id=user_id, target_id=target_id, session_id=session_id, limit=limit
        )
