from __future__ import annotations

from datetime import datetime

from sqlalchemy import and_, or_, select, update
from sqlalchemy.orm import Session

from app.models.agent_operation import AgentOperation


class AgentOperationRepository:
    def __init__(self, db: Session):
        self.db = db

    def create(self, entry: AgentOperation) -> AgentOperation:
        self.db.add(entry)
        self.db.commit()
        self.db.refresh(entry)
        return entry

    def get(self, operation_id: str) -> AgentOperation | None:
        statement = (
            select(AgentOperation)
            .where(AgentOperation.id == operation_id)
            .execution_options(populate_existing=True)
        )
        return self.db.scalars(statement).first()

    def save(self, entry: AgentOperation) -> AgentOperation:
        self.db.add(entry)
        self.db.commit()
        self.db.refresh(entry)
        return entry

    def claim_next(
        self,
        *,
        agent_id: str,
        now: datetime,
        lease_expires_at: datetime,
        allowed_operations: list[str],
    ) -> AgentOperation | None:
        statement = (
            select(AgentOperation)
            .where(
                AgentOperation.agent_id == agent_id,
                AgentOperation.operation.in_(allowed_operations),
                or_(
                    AgentOperation.status == "pending",
                    and_(
                        AgentOperation.status == "in_progress",
                        AgentOperation.lease_expires_at.is_not(None),
                        AgentOperation.lease_expires_at <= now,
                    ),
                ),
            )
            .order_by(AgentOperation.requested_at.asc())
        )
        operation = self.db.scalars(statement).first()
        if operation is None:
            return None

        operation.status = "in_progress"
        operation.dispatched_at = now
        operation.lease_expires_at = lease_expires_at
        self.db.commit()
        self.db.refresh(operation)
        return operation

    def expire_stale(self, *, agent_id: str, now: datetime, pending_before: datetime) -> int:
        """Time out operations whose lease lapsed or that nobody claimed in time."""
        result = self.db.execute(
            update(AgentOperation)
            .where(
                AgentOperation.agent_id == agent_id,
                or_(
                    and_(
                        AgentOperation.status == "in_progress",
                        AgentOperation.lease_expires_at.is_not(None),
                        AgentOperation.lease_expires_at <= now,
                    ),
                    and_(
                        AgentOperation.status == "pending",
                        AgentOperation.requested_at <= pending_before,
                    ),
                ),
            )
            .values(
                status="timed_out",
                detail="Operation expired before the Agent completed it",
                completed_at=now,
                lease_expires_at=None,
            )
        )
        self.db.commit()
        return result.rowcount
