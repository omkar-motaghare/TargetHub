from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.models.lab import WaitlistEntry
from app.models.reservation import Reservation
from app.models.target import Target


class ReservationRepository:
    def __init__(self, db: Session):
        self.db = db

    def list(
        self,
        target_id: str | None = None,
        user_id: str | None = None,
        status: str | None = None,
        starts_before: datetime | None = None,
        ends_after: datetime | None = None,
        limit: int | None = None,
    ):
        query = self.db.query(Reservation)
        if target_id is not None:
            query = query.filter(Reservation.target_id == target_id)
        if user_id is not None:
            query = query.filter(Reservation.user_id == user_id)
        if status is not None:
            query = query.filter(Reservation.status == status)
        if starts_before is not None:
            query = query.filter(Reservation.starts_at < starts_before)
        if ends_after is not None:
            query = query.filter(Reservation.ends_at > ends_after)
        query = query.order_by(Reservation.starts_at.asc())
        if limit:
            query = query.limit(limit)
        return query.all()

    def active_by_target(self) -> dict[str, list[Reservation]]:
        grouped: dict[str, list[Reservation]] = {}
        for reservation in self.db.query(Reservation).filter(Reservation.status == "active").all():
            grouped.setdefault(reservation.target_id, []).append(reservation)
        return grouped

    def count_active_for_user(self, user_id: str) -> int:
        return int(
            self.db.scalar(
                select(func.count()).where(Reservation.user_id == user_id, Reservation.status == "active")
            )
            or 0
        )

    def last_used_at(self, target_id: str) -> datetime | None:
        return self.db.scalar(select(func.max(Reservation.ends_at)).where(Reservation.target_id == target_id))

    def has_waiters(self, target_id: str) -> bool:
        target = self.db.get(Target, target_id)
        tags = list(target.tags or []) if target else []
        statement = select(func.count()).where(WaitlistEntry.status == "waiting")
        condition = WaitlistEntry.target_id == target_id
        if tags:
            condition = condition | WaitlistEntry.tag.in_(tags)
        return bool(self.db.scalar(statement.where(condition)))

    def get(self, reservation_id: str):
        return (
            self.db.query(Reservation)
            .filter(Reservation.id == reservation_id)
            .first()
        )

    def lock_target(self, target_id: str) -> None:
        # No-op write: row lock on Postgres, write lock on SQLite. Held until commit,
        # so the overlap check and insert run serialized per target.
        self.db.execute(
            update(Target).where(Target.id == target_id).values(updated_at=Target.updated_at)
        )

    def find_overlapping_active(
        self,
        target_id: str,
        starts_at: datetime,
        ends_at: datetime,
        exclude_id: str | None = None,
    ):
        query = self.db.query(Reservation).filter(
            Reservation.target_id == target_id,
            Reservation.status == "active",
            Reservation.starts_at < ends_at,
            Reservation.ends_at > starts_at,
        )
        if exclude_id:
            query = query.filter(Reservation.id != exclude_id)
        return query.order_by(Reservation.starts_at.asc()).first()

    def expire_due(self, now: datetime) -> int:
        return len(self.expire_due_list(now))

    def expire_due_list(self, now: datetime) -> list[Reservation]:
        """Expire reservations whose window ended; returns the ones this call expired."""
        due = list(
            self.db.scalars(
                select(Reservation).where(Reservation.status == "active", Reservation.ends_at <= now)
            ).all()
        )
        expired = []
        for reservation in due:
            changed = self.db.execute(
                update(Reservation)
                .where(Reservation.id == reservation.id, Reservation.status == "active")
                .values(status="expired", updated_at=now)
            ).rowcount
            if changed:
                expired.append(reservation)
        self.db.commit()
        for reservation in expired:
            self.db.refresh(reservation)
        return expired

    def create(self, reservation: Reservation):
        self.db.add(reservation)
        self.db.commit()
        self.db.refresh(reservation)
        return reservation

    def update(self, reservation: Reservation):
        self.db.commit()
        self.db.refresh(reservation)
        return reservation
