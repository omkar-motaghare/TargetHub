import uuid
from datetime import datetime, timezone

from app.core.exceptions import ConflictResource, ResourceNotFound
from app.models.reservation import Reservation
from app.repositories.reservation_repository import ReservationRepository
from app.repositories.target_repository import TargetRepository


class ReservationService:
    def __init__(self, repository: ReservationRepository, target_repository: TargetRepository):
        self.repository = repository
        self.target_repository = target_repository

    def list_reservations(self, target_id: str | None = None, user_id: str | None = None):
        self.repository.expire_due(datetime.now(timezone.utc))
        return self.repository.list(target_id=target_id, user_id=user_id)

    def get_reservation(self, reservation_id: str):
        reservation = self.repository.get(reservation_id)
        if reservation is None:
            raise ResourceNotFound("Reservation", reservation_id)
        return reservation

    def create_reservation(
        self,
        target_id: str,
        user_id: str,
        starts_at: datetime,
        ends_at: datetime,
    ):
        target = self.target_repository.get(target_id)
        if target is None:
            raise ResourceNotFound("Target", target_id)
        if not target.enabled:
            raise ConflictResource("Target is disabled")
        if target.status != "available":
            raise ConflictResource(
                f"Target '{target_id}' is not operationally available"
            )

        if starts_at.tzinfo is None or ends_at.tzinfo is None:
            raise ConflictResource("starts_at and ends_at must include a timezone")
        if ends_at <= starts_at:
            raise ConflictResource("ends_at must be after starts_at")

        starts_at = starts_at.astimezone(timezone.utc)
        ends_at = ends_at.astimezone(timezone.utc)
        self.repository.expire_due(datetime.now(timezone.utc))

        conflict = self.repository.find_overlapping_active(
            target_id,
            starts_at,
            ends_at,
        )
        if conflict is not None:
            raise ConflictResource(
                f"Target '{target_id}' is already reserved from "
                f"{conflict.starts_at.isoformat()} to {conflict.ends_at.isoformat()}"
            )

        reservation = Reservation(
            id=str(uuid.uuid4()),
            target_id=target_id,
            user_id=user_id,
            starts_at=starts_at,
            ends_at=ends_at,
            status="active",
        )
        return self.repository.create(reservation)

    def release_reservation(self, reservation_id: str, user_id: str):
        reservation = self.get_reservation(reservation_id)
        if reservation.user_id != user_id:
            raise ConflictResource("Only the reservation owner can release it")
        if reservation.status != "active":
            raise ConflictResource(
                f"Reservation '{reservation_id}' is already {reservation.status}"
            )

        reservation.status = "released"
        reservation.released_at = datetime.now(timezone.utc)
        return self.repository.update(reservation)
