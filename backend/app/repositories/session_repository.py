from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.session import TargetSession


class SessionRepository:
    def __init__(self, db: Session):
        self.db = db

    def create(self, session: TargetSession) -> TargetSession:
        self.db.add(session)
        self.db.commit()
        self.db.refresh(session)
        return session

    def get(self, session_id: str) -> TargetSession | None:
        return self.db.get(TargetSession, session_id)

    def list(self, user_id: str | None = None, target_id: str | None = None):
        statement = select(TargetSession).order_by(TargetSession.created_at.desc())
        if user_id:
            statement = statement.where(TargetSession.user_id == user_id)
        if target_id:
            statement = statement.where(TargetSession.target_id == target_id)
        return list(self.db.scalars(statement).all())

    def expire_due(self, now: datetime) -> int:
        statement = select(TargetSession).where(
            TargetSession.status == "active",
            TargetSession.expires_at <= now,
        )
        sessions = list(self.db.scalars(statement).all())
        for session in sessions:
            session.status = "expired"
            session.ended_at = now
        if sessions:
            self.db.commit()
        return len(sessions)

    def update(self, session: TargetSession) -> TargetSession:
        self.db.add(session)
        self.db.commit()
        self.db.refresh(session)
        return session
