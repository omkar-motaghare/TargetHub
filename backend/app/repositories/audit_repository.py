from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.audit import AuditLog


class AuditRepository:
    def __init__(self, db: Session):
        self.db = db

    def create(self, entry: AuditLog) -> AuditLog:
        self.db.add(entry)
        self.db.commit()
        self.db.refresh(entry)
        return entry

    def list(
        self,
        user_id: str | None = None,
        target_id: str | None = None,
        session_id: str | None = None,
        action: str | None = None,
        limit: int = 200,
    ) -> list[AuditLog]:
        statement = select(AuditLog).order_by(AuditLog.created_at.desc())
        if user_id:
            statement = statement.where(AuditLog.user_id == user_id)
        if target_id:
            statement = statement.where(AuditLog.target_id == target_id)
        if session_id:
            statement = statement.where(AuditLog.session_id == session_id)
        if action:
            statement = statement.where(AuditLog.action == action)
        statement = statement.limit(limit)
        return list(self.db.scalars(statement).all())
