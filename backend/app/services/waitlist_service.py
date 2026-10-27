"""Waitlist: queue for a busy target (or any target with a tag); auto-reserve when free."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.exceptions import ConflictResource, ResourceNotFound
from app.core.logging import logger
from app.models.lab import WaitlistEntry
from app.repositories.reservation_repository import ReservationRepository
from app.repositories.session_repository import SessionRepository
from app.repositories.target_repository import TargetRepository
from app.services.lab_settings import LabSettings
from app.services.notifier import Notifier
from app.services.reservation_service import ReservationService


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


class WaitlistService:
    def __init__(self, db: Session):
        self.db = db
        self.targets = TargetRepository(db)
        self.policy = LabSettings(db).policy()
        self.notifier = Notifier(db)

    def _reservations(self) -> ReservationService:
        return ReservationService(
            ReservationRepository(self.db),
            self.targets,
            SessionRepository(self.db),
            policy=self.policy,
            notifier=self.notifier,
        )

    def join(
        self,
        user_id: str,
        *,
        target_id: str | None,
        tag: str | None,
        duration_minutes: int,
        note: str | None = None,
    ) -> WaitlistEntry:
        if bool(target_id) == bool(tag):
            raise ConflictResource("Join the waitlist for exactly one of target_id or tag")
        if duration_minutes > self.policy.max_duration_minutes:
            raise ConflictResource(
                f"Reservations are limited to {self.policy.max_duration_minutes} minutes by lab policy"
            )
        if target_id:
            target = self.targets.get(target_id)
            if target is None:
                raise ResourceNotFound("Target", target_id)
            if not target.enabled or target.status == "retired":
                raise ConflictResource("Target is not reservable")
        elif not self.targets.list(tag=tag):
            raise ResourceNotFound("Target with tag", tag or "")
        duplicate = self.db.scalar(
            select(WaitlistEntry).where(
                WaitlistEntry.user_id == user_id,
                WaitlistEntry.status == "waiting",
                WaitlistEntry.target_id == target_id if target_id else WaitlistEntry.tag == tag,
            )
        )
        if duplicate is not None:
            raise ConflictResource("You are already on this waitlist")
        entry = WaitlistEntry(
            user_id=user_id,
            target_id=target_id,
            tag=tag,
            duration_minutes=duration_minutes,
            note=note,
            status="waiting",
            expires_at=datetime.now(UTC) + timedelta(hours=self.policy.waitlist_entry_ttl_hours),
        )
        self.db.add(entry)
        self.db.commit()
        self.db.refresh(entry)
        return entry

    def leave(self, user_id: str, entry_id: str, privileged: bool = False) -> WaitlistEntry:
        entry = self.db.get(WaitlistEntry, entry_id)
        if entry is None or (entry.user_id != user_id and not privileged):
            raise ResourceNotFound("Waitlist entry", entry_id)
        if entry.status != "waiting":
            raise ConflictResource(f"Waitlist entry is already {entry.status}")
        entry.status = "cancelled"
        self.db.commit()
        return entry

    def list(self, user_id: str | None = None, target_id: str | None = None, active_only: bool = True):
        statement = select(WaitlistEntry).order_by(WaitlistEntry.created_at.asc())
        if user_id:
            statement = statement.where(WaitlistEntry.user_id == user_id)
        if target_id:
            target = self.targets.get(target_id)
            tags = list(target.tags or []) if target else []
            condition = WaitlistEntry.target_id == target_id
            if tags:
                condition = condition | WaitlistEntry.tag.in_(tags)
            statement = statement.where(condition)
        if active_only:
            statement = statement.where(WaitlistEntry.status == "waiting")
        return list(self.db.scalars(statement).all())

    def position(self, entry: WaitlistEntry) -> int:
        """1-based place in its queue (same target, or same tag); 0 when not waiting."""
        if entry.status != "waiting":
            return 0
        same_queue = WaitlistEntry.target_id == entry.target_id if entry.target_id else WaitlistEntry.tag == entry.tag
        ahead = self.db.scalars(
            select(WaitlistEntry.id).where(
                same_queue, WaitlistEntry.status == "waiting", WaitlistEntry.created_at <= entry.created_at
            )
        ).all()
        return len(ahead)

    def _claim(self, entry_id: str, from_status: str, to_status: str) -> bool:
        changed = self.db.execute(
            update(WaitlistEntry)
            .where(WaitlistEntry.id == entry_id, WaitlistEntry.status == from_status)
            .values(status=to_status)
        ).rowcount
        self.db.commit()
        return changed == 1

    def process(self, now: datetime | None = None) -> int:
        """Fulfil waiting entries in FIFO order; returns how many got a reservation."""
        now = now or datetime.now(UTC)
        fulfilled = 0
        entries = list(
            self.db.scalars(
                select(WaitlistEntry).where(WaitlistEntry.status == "waiting").order_by(WaitlistEntry.created_at.asc())
            ).all()
        )
        for entry in entries:
            if _as_utc(entry.expires_at) and _as_utc(entry.expires_at) <= now:
                if self._claim(entry.id, "waiting", "expired"):
                    self.notifier.event(
                        "waitlist.expired",
                        "Your waitlist entry expired before a target became free",
                        user_id=entry.user_id,
                        target_id=entry.target_id,
                    )
                continue
            if not self._claim(entry.id, "waiting", "processing"):
                continue
            reservation = None
            try:
                service = self._reservations()
                if entry.target_id:
                    reservation = service.create_reservation(
                        entry.target_id,
                        entry.user_id,
                        now,
                        now + timedelta(minutes=entry.duration_minutes),
                        note=entry.note or "via waitlist",
                    )
                else:
                    reservation = service.reserve_any(
                        entry.tag, entry.user_id, entry.duration_minutes, now, note=entry.note or "via waitlist"
                    )
            except (ConflictResource, ResourceNotFound):
                reservation = None
            except Exception as exc:  # pragma: no cover - keep the queue moving
                logger.warning(f"waitlist entry {entry.id} failed: {exc}")
                reservation = None
            if reservation is None:
                self._claim(entry.id, "processing", "waiting")
                continue
            entry = self.db.get(WaitlistEntry, entry.id)
            entry.status = "fulfilled"
            entry.reservation_id = reservation.id
            entry.fulfilled_at = now
            self.db.commit()
            fulfilled += 1
            target = self.targets.get(reservation.target_id)
            name = target.name if target else reservation.target_id
            self.notifier.event(
                "waitlist.fulfilled",
                f"[{name}] is now reserved for {entry.user_id} until {_as_utc(reservation.ends_at):%H:%M} UTC",
                user_id=entry.user_id,
                target_id=reservation.target_id,
                reservation_id=reservation.id,
                data={"target": name, "user_id": entry.user_id, "reservation_id": reservation.id},
            )
        return fulfilled
