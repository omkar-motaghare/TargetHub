from datetime import datetime

from sqlalchemy import and_, or_, update
from sqlalchemy.orm import Session

from app.models.reservation import Reservation


class ReservationRepository:
    def __init__(self, db: Session):
        self.db = db

    def list(self, target_id: str | None = None, user_id: str | None = None):
        query = self.db.query(Reservation)
        if target_id is not None:
            query = query.filter(Reservation.target_id == target_id)
        if user_id is not None:
            query = query.filter(Reservation.user_id == user_id)
        return query.order_by(Reservation.starts_at.asc()).all()

    def get(self, reservation_id: str):
        return (
            self.db.query(Reservation)
            .filter(Reservation.id == reservation_id)
            .first()
        )

    def find_overlapping_active(
        self,
        target_id: str,
        starts_at: datetime,
        ends_at: datetime,
    ):
        return (
            self.db.query(Reservation)
            .filter(
                Reservation.target_id == target_id,
                Reservation.status == "active",
                Reservation.starts_at < ends_at,
                Reservation.ends_at > starts_at,
            )
            .order_by(Reservation.starts_at.asc())
            .first()
        )

    def expire_due(self, now: datetime) -> int:
        result = self.db.execute(
            update(Reservation)
            .where(
                Reservation.status == "active",
                Reservation.ends_at <= now,
            )
            .values(status="expired", updated_at=now)
        )
        self.db.commit()
        return result.rowcount

    def create(self, reservation: Reservation):
        self.db.add(reservation)
        self.db.commit()
        self.db.refresh(reservation)
        return reservation

    def update(self, reservation: Reservation):
        self.db.commit()
        self.db.refresh(reservation)
        return reservation
