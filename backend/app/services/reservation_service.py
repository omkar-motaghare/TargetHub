from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from app.core.exceptions import ConflictResource, ResourceNotFound
from app.models.reservation import Reservation
from app.repositories.reservation_repository import ReservationRepository
from app.repositories.session_repository import SessionRepository
from app.repositories.target_repository import TargetRepository
from app.services.lab_settings import ReservationPolicy

# Clock skew tolerated for "start now" requests from clients.
START_SKEW = timedelta(minutes=5)


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


class ReservationService:
    def __init__(
        self,
        repository: ReservationRepository,
        target_repository: TargetRepository,
        session_repository: SessionRepository,
        policy: ReservationPolicy | None = None,
        notifier=None,
    ):
        self.repository = repository
        self.target_repository = target_repository
        self.session_repository = session_repository
        self.policy = policy or ReservationPolicy()
        self.notifier = notifier

    # ------------------------------------------------------------------ queries

    def list_reservations(self, target_id: str | None = None, user_id: str | None = None, **filters):
        self.repository.expire_due(datetime.now(UTC))
        return self.repository.list(target_id=target_id, user_id=user_id, **filters)

    def get_reservation(self, reservation_id: str):
        reservation = self.repository.get(reservation_id)
        if reservation is None:
            raise ResourceNotFound("Reservation", reservation_id)
        return reservation

    # ------------------------------------------------------------------ policy

    def _check_target(self, target_id: str):
        target = self.target_repository.get(target_id)
        if target is None:
            raise ResourceNotFound("Target", target_id)
        if not target.enabled:
            raise ConflictResource("Target is disabled")
        if target.status != "available":
            reason = f": {target.status_reason}" if getattr(target, "status_reason", None) else ""
            raise ConflictResource(f"Target '{target.name}' is in {target.status}{reason}")
        return target

    def _check_window(self, starts_at: datetime, ends_at: datetime, *, now: datetime, privileged: bool) -> None:
        if starts_at.tzinfo is None or ends_at.tzinfo is None:
            raise ConflictResource("starts_at and ends_at must include a timezone")
        if ends_at <= starts_at:
            raise ConflictResource("ends_at must be after starts_at")
        if ends_at <= now:
            raise ConflictResource("Reservation would already be over")
        if privileged:
            return
        if starts_at < now - START_SKEW:
            raise ConflictResource("Reservations cannot start in the past")
        duration = ends_at - starts_at
        if duration > timedelta(minutes=self.policy.max_duration_minutes):
            raise ConflictResource(
                f"Reservations are limited to {self.policy.max_duration_minutes} minutes by lab policy"
            )
        if starts_at > now + timedelta(days=self.policy.max_advance_days):
            raise ConflictResource(
                f"Reservations can be made at most {self.policy.max_advance_days} days ahead"
            )

    def _check_user_quota(self, user_id: str, privileged: bool) -> None:
        limit = self.policy.max_active_reservations_per_user
        if privileged or not limit:
            return
        if self.repository.count_active_for_user(user_id) >= limit:
            raise ConflictResource(f"Lab policy allows at most {limit} active reservations per user")

    # ------------------------------------------------------------------ create

    def create_reservation(
        self,
        target_id: str,
        user_id: str,
        starts_at: datetime,
        ends_at: datetime,
        note: str | None = None,
        privileged: bool = False,
    ):
        target = self._check_target(target_id)
        now = datetime.now(UTC)
        self._check_window(starts_at, ends_at, now=now, privileged=privileged)
        starts_at = starts_at.astimezone(UTC)
        ends_at = ends_at.astimezone(UTC)
        self.repository.expire_due(now)
        self._check_user_quota(user_id, privileged)

        self.repository.lock_target(target_id)
        conflict = self.repository.find_overlapping_active(target_id, starts_at, ends_at)
        if conflict is not None:
            self.repository.db.rollback()
            raise ConflictResource(
                f"Target '{target.name}' is already reserved by {conflict.user_id} from "
                f"{_as_utc(conflict.starts_at).isoformat()} to {_as_utc(conflict.ends_at).isoformat()}"
            )

        reservation = Reservation(
            id=str(uuid.uuid4()),
            target_id=target_id,
            user_id=user_id,
            starts_at=starts_at,
            ends_at=ends_at,
            status="active",
            note=(note or None),
        )
        created = self.repository.create(reservation)
        self._event(
            "reservation.created",
            f"{user_id} reserved {target.name} until {ends_at:%Y-%m-%d %H:%M} UTC",
            created,
        )
        return created

    def reserve_any(
        self,
        tag: str,
        user_id: str,
        duration_minutes: int,
        starts_at: datetime | None = None,
        note: str | None = None,
        privileged: bool = False,
    ):
        """Reserve the first free target carrying ``tag`` for the requested window."""
        now = datetime.now(UTC)
        starts_at = (starts_at or now).astimezone(UTC)
        ends_at = starts_at + timedelta(minutes=duration_minutes)
        candidates = [
            target
            for target in self.target_repository.list(tag=tag)
            if target.enabled and target.status == "available"
        ]
        if not candidates:
            raise ResourceNotFound("Available target with tag", tag)
        # Prefer the least recently reserved board to spread wear and usage.
        def last_used(target) -> datetime:
            value = self.repository.last_used_at(target.id)
            return _as_utc(value) if value else datetime.min.replace(tzinfo=UTC)

        candidates.sort(key=last_used)
        last_error: ConflictResource | None = None
        for target in candidates:
            try:
                return self.create_reservation(target.id, user_id, starts_at, ends_at, note, privileged)
            except ConflictResource as exc:
                last_error = exc
                if "per user" in str(exc) or "policy" in str(exc) or "past" in str(exc) or "ahead" in str(exc):
                    raise
        raise ConflictResource(f"All targets tagged '{tag}' are busy for that window") from last_error

    # ------------------------------------------------------------------ change

    def extend_reservation(self, reservation_id: str, user_id: str, ends_at: datetime, privileged: bool = False):
        reservation = self.get_reservation(reservation_id)
        if reservation.user_id != user_id and not privileged:
            raise ConflictResource("Only the reservation owner can extend it")
        now = datetime.now(UTC)
        self.repository.expire_due(now)
        if reservation.status != "active":
            raise ConflictResource(f"Reservation is {reservation.status}")
        if ends_at.tzinfo is None:
            raise ConflictResource("ends_at must include a timezone")
        ends_at = ends_at.astimezone(UTC)
        current_end = _as_utc(reservation.ends_at)
        if ends_at <= current_end:
            raise ConflictResource("New end time must be later than the current end time")
        starts_at = _as_utc(reservation.starts_at)
        if not privileged:
            limit = timedelta(minutes=self.policy.max_duration_minutes)
            if ends_at - starts_at > limit:
                raise ConflictResource(
                    f"Reservations are limited to {self.policy.max_duration_minutes} minutes by lab policy"
                )
            if not self.policy.allow_extend_when_waitlisted and self.repository.has_waiters(reservation.target_id):
                raise ConflictResource("Someone is waiting for this target; release it or ask an admin to extend")

        self.repository.lock_target(reservation.target_id)
        conflict = self.repository.find_overlapping_active(
            reservation.target_id, current_end, ends_at, exclude_id=reservation.id
        )
        if conflict is not None:
            self.repository.db.rollback()
            raise ConflictResource(
                f"Cannot extend: {conflict.user_id} has the target from {_as_utc(conflict.starts_at).isoformat()}"
            )
        reservation.ends_at = ends_at
        reservation.warned_at = None
        updated = self.repository.update(reservation)
        self.session_repository.extend_for_reservation(reservation.id, ends_at)
        self._event("reservation.extended", f"{reservation.user_id} extended their reservation until {ends_at:%H:%M} UTC", updated)
        return updated

    def _end(self, reservation, actor: str, status: str = "released"):
        now = datetime.now(UTC)
        reservation.status = status
        reservation.released_at = now
        reservation.released_by = actor
        self.session_repository.close_active_for_reservation(reservation.id, now)
        return self.repository.update(reservation)

    def release_reservation(self, reservation_id: str, user_id: str):
        reservation = self.get_reservation(reservation_id)
        if reservation.user_id != user_id:
            raise ConflictResource("Only the reservation owner can release it")
        if reservation.status != "active":
            raise ConflictResource(f"Reservation '{reservation_id}' is already {reservation.status}")
        released = self._end(reservation, user_id)
        self._event("reservation.released", f"{user_id} released their reservation", released)
        return released

    def force_release_reservation(self, reservation_id: str, actor: str = "admin"):
        reservation = self.get_reservation(reservation_id)
        if reservation.status != "active":
            raise ConflictResource(f"Reservation '{reservation_id}' is already {reservation.status}")
        released = self._end(reservation, actor)
        self._event(
            "reservation.released",
            f"{actor} force-released the reservation of {reservation.user_id}",
            released,
            notify=reservation.user_id,
        )
        return released

    # ------------------------------------------------------------------ helpers

    def _event(self, event: str, message: str, reservation, notify: str | None = None) -> None:
        if self.notifier is None:
            return
        target = self.target_repository.get(reservation.target_id)
        name = target.name if target else reservation.target_id
        self.notifier.event(
            event,
            f"[{name}] {message}",
            user_id=notify,
            target_id=reservation.target_id,
            reservation_id=reservation.id,
            data={
                "reservation_id": reservation.id,
                "target_id": reservation.target_id,
                "target": name,
                "user_id": reservation.user_id,
                "starts_at": _as_utc(reservation.starts_at).isoformat(),
                "ends_at": _as_utc(reservation.ends_at).isoformat(),
                "status": reservation.status,
            },
        )


def availability(target, active_reservations: list, now: datetime | None = None) -> dict:
    """Who holds a target now and when it is next booked (shown to every user)."""
    now = now or datetime.now(UTC)
    if not target.enabled:
        state = "disabled"
    elif target.status != "available":
        state = target.status
    else:
        state = "available"
    current = None
    upcoming = None
    for reservation in sorted(active_reservations, key=lambda item: _as_utc(item.starts_at)):
        start, end = _as_utc(reservation.starts_at), _as_utc(reservation.ends_at)
        if start <= now < end and current is None:
            current = reservation
        elif start > now and upcoming is None:
            upcoming = reservation
    if current is not None and state == "available":
        state = "reserved"
    return {
        "state": state,
        "reason": getattr(target, "status_reason", None),
        "reserved_by": current.user_id if current else None,
        "reserved_until": _as_utc(current.ends_at) if current else None,
        "next_reservation_at": _as_utc(upcoming.starts_at) if upcoming else None,
        "next_reserved_by": upcoming.user_id if upcoming else None,
    }
