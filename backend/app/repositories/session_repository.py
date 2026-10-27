from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.agent import AgentResource
from app.models.agent_operation import AgentOperation
from app.models.session import TargetSession

# Capability types whose Agent keeps per-session hardware state (an open port).
AGENT_STATEFUL_CAPABILITIES = {"serial"}


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
            self._queue_agent_cleanup(sessions)
            self.db.commit()
            self._notify_agents(sessions)
        return len(sessions)

    def update(self, session: TargetSession) -> TargetSession:
        self.db.add(session)
        self.db.commit()
        self.db.refresh(session)
        return session

    def close_active_for_reservation(self, reservation_id: str, now: datetime) -> int:
        statement = select(TargetSession).where(
            TargetSession.reservation_id == reservation_id,
            TargetSession.status == "active",
        )
        sessions = list(self.db.scalars(statement).all())
        for session in sessions:
            session.status = "closed"
            session.ended_at = now
        if sessions:
            self._queue_agent_cleanup(sessions)
            self.db.commit()
            self._notify_agents(sessions)
        return len(sessions)

    def close(self, session: TargetSession, now: datetime, status: str = "closed") -> TargetSession:
        """End one session and queue release of any Agent-held hardware."""
        session.status = status
        session.ended_at = now
        self.db.add(session)
        self._queue_agent_cleanup([session])
        self.db.commit()
        self._notify_agents([session])
        self.db.refresh(session)
        return session

    def _queue_agent_cleanup(self, sessions: list[TargetSession]) -> None:
        """Add (uncommitted) close operations so the Agent frees ports of ended sessions."""
        for session in sessions:
            if (
                session.capability_type not in AGENT_STATEFUL_CAPABILITIES
                or not session.agent_id
                or not session.resource_id
            ):
                continue
            resource = self.db.get(AgentResource, session.resource_id)
            if resource is None or resource.agent_id != session.agent_id:
                continue
            self.db.add(
                AgentOperation(
                    agent_id=session.agent_id,
                    session_id=session.id,
                    resource_id=session.resource_id,
                    resource_key=resource.resource_key,
                    resource_type=resource.resource_type,
                    resource_metadata=resource.resource_metadata or {},
                    operation="close",
                    params={"cleanup": True},
                    status="pending",
                    requested_by="system",
                    detached=True,
                )
            )

    @staticmethod
    def _notify_agents(sessions: list[TargetSession]) -> None:
        from app.services.operation_signals import agent_key, signals

        for agent_id in {session.agent_id for session in sessions if session.agent_id}:
            signals.notify(agent_key(agent_id))
