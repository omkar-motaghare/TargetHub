"""Periodic lab maintenance: expiry, warnings, waitlist, agent liveness, retention.

Every API worker runs the loop; each step is idempotent (conditional
updates), so running it concurrently is safe.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.core.config import settings
from app.core.logging import logger
from app.core.metrics import metrics
from app.db.models.tokens import RefreshToken
from app.models.agent import Agent
from app.models.agent_operation import AgentOperation
from app.models.audit import AuditLog
from app.models.lab import Notification, WaitlistEntry
from app.models.reservation import Reservation
from app.models.session import TargetSession
from app.models.target import Target
from app.repositories.agent_repository import AgentRepository
from app.repositories.reservation_repository import ReservationRepository
from app.repositories.serial_log_repository import SerialLogRepository
from app.repositories.session_repository import SessionRepository
from app.services.agent_service import AgentService
from app.services.lab_settings import LabSettings
from app.services.notifier import Notifier
from app.services.waitlist_service import WaitlistService

OPERATION_RETENTION = timedelta(days=2)
NOTIFICATION_RETENTION = timedelta(days=90)


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _target_name(db: Session, target_id: str) -> str:
    target = db.get(Target, target_id)
    return target.name if target else target_id


def run_maintenance(db: Session, now: datetime | None = None) -> dict[str, int]:
    now = now or datetime.now(UTC)
    policy = LabSettings(db).policy()
    notifier = Notifier(db)
    stats: dict[str, int] = {}

    # 1. Reservations whose window ended.
    expired = ReservationRepository(db).expire_due_list(now)
    for reservation in expired:
        name = _target_name(db, reservation.target_id)
        notifier.event(
            "reservation.expired",
            f"[{name}] reservation of {reservation.user_id} ended",
            user_id=reservation.user_id,
            target_id=reservation.target_id,
            reservation_id=reservation.id,
            data={"target": name, "user_id": reservation.user_id, "reservation_id": reservation.id},
        )
    stats["reservations_expired"] = len(expired)

    # 2. Sessions past expiry (queues Agent cleanup).
    stats["sessions_expired"] = SessionRepository(db).expire_due(now)

    # 3. "Ending soon" warnings, once per reservation (window).
    warned = 0
    if policy.expiry_warning_minutes:
        soon = now + timedelta(minutes=policy.expiry_warning_minutes)
        candidates = db.scalars(
            select(Reservation).where(
                Reservation.status == "active",
                Reservation.warned_at.is_(None),
                Reservation.ends_at <= soon,
                Reservation.ends_at > now,
                Reservation.starts_at <= now,
            )
        ).all()
        for reservation in candidates:
            claimed = db.execute(
                update(Reservation)
                .where(Reservation.id == reservation.id, Reservation.warned_at.is_(None))
                .values(warned_at=now)
            ).rowcount
            db.commit()
            if not claimed:
                continue
            warned += 1
            minutes = max(1, int((_as_utc(reservation.ends_at) - now).total_seconds() // 60))
            name = _target_name(db, reservation.target_id)
            notifier.event(
                "reservation.expiring",
                f"[{name}] reservation of {reservation.user_id} ends in {minutes} min — extend or wrap up",
                user_id=reservation.user_id,
                target_id=reservation.target_id,
                reservation_id=reservation.id,
                data={"target": name, "user_id": reservation.user_id, "minutes_left": minutes},
            )
    stats["expiry_warnings"] = warned

    # 4. Waitlist.
    stats["waitlist_fulfilled"] = WaitlistService(db).process(now)

    # 5. Agent liveness transitions (announced as agent.offline by the service).
    stats["agents_offline"] = len(AgentService(AgentRepository(db)).mark_stale_offline())

    # 6. Retention.
    stats["transcripts_purged"] = SerialLogRepository(db).purge_before(
        now - timedelta(days=policy.transcript_retention_days)
    )
    stats["operations_purged"] = db.execute(
        delete(AgentOperation).where(
            AgentOperation.status.in_(("completed", "failed", "cancelled", "timed_out")),
            AgentOperation.requested_at < now - OPERATION_RETENTION,
        )
    ).rowcount or 0
    db.execute(delete(Notification).where(Notification.created_at < now - NOTIFICATION_RETENTION))
    db.execute(delete(RefreshToken).where(RefreshToken.expires_at < now - timedelta(days=1)))
    stats["audit_purged"] = db.execute(
        delete(AuditLog).where(AuditLog.created_at < now - timedelta(days=policy.audit_retention_days))
    ).rowcount or 0
    db.commit()

    # Gauges for dashboards.
    metrics.set_gauge(
        "targethub_reservations_active",
        float(db.query(Reservation).filter(Reservation.status == "active").count()),
    )
    metrics.set_gauge(
        "targethub_agents_online",
        float(db.query(Agent).filter(Agent.status == "online").count()),
    )
    metrics.set_gauge(
        "targethub_sessions_active",
        float(db.query(TargetSession).filter(TargetSession.status == "active").count()),
    )
    metrics.set_gauge(
        "targethub_waitlist_waiting",
        float(db.query(WaitlistEntry).filter(WaitlistEntry.status == "waiting").count()),
    )
    return stats


def _session_factory(app):
    factory = getattr(app.state, "session_factory", None)
    if factory is not None:
        return factory
    from app.db.session import SessionLocal

    return SessionLocal


def _tick(app) -> dict[str, int]:
    db = _session_factory(app)()
    try:
        return run_maintenance(db)
    finally:
        db.close()


async def scheduler_loop(app, stop: asyncio.Event) -> None:
    interval = max(5, settings.scheduler_interval_seconds)
    logger.info(f"Lab scheduler running every {interval}s")
    while not stop.is_set():
        try:
            stats = await run_in_threadpool(_tick, app)
            busy = {key: value for key, value in stats.items() if value}
            if busy:
                logger.info(f"scheduler: {busy}")
        except Exception as exc:
            logger.warning(f"scheduler tick failed: {exc}")
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval)
        except TimeoutError:
            pass
