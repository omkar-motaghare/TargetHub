"""Board health checks: power a target, expect a boot banner on its console, quarantine it if that fails.

A check books the target like a user would (as the ``healthcheck`` user), so it can never run on a board
somebody is using, and it uses the normal session and provider code paths. Boards that fail
``failure_threshold`` checks in a row are put into maintenance with a visible reason; a board that the
check itself quarantined is checked again on schedule and returns to service when it passes.
"""

from __future__ import annotations

import time
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.core.exceptions import ConflictResource, ResourceNotFound
from app.core.logging import logger
from app.core.metrics import metrics
from app.models.health_check import HealthCheck, HealthCheckResult
from app.models.reservation import Reservation
from app.models.target import Target
from app.repositories.reservation_repository import ReservationRepository
from app.repositories.session_repository import SessionRepository
from app.repositories.target_repository import TargetRepository
from app.services.notifier import Notifier
from app.services.session_service import SessionService

HEALTH_USER = "healthcheck"
POWER_OPERATIONS = ("cycle", "reset", "on")
RESULTS_KEPT_PER_TARGET = 100
RESULT_RETENTION = timedelta(days=90)
MAX_CHECKS_PER_TICK = 3
RESERVATION_MARGIN_SECONDS = 90
MAINTENANCE_PREFIX = "Health check failed"


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


class _Skip(Exception):
    """The check cannot run now (not an unhealthy board)."""


class _Prepared:
    def __init__(self, reservation_id: str, serial_id: str, power_id: str, cfg: HealthCheck):
        self.reservation_id = reservation_id
        self.serial_id = serial_id
        self.power_id = power_id
        self.pattern = cfg.boot_pattern
        self.timeout = cfg.boot_timeout_seconds
        self.power_operation = cfg.power_operation


# ------------------------------------------------------------------------------- configuration


def get_config(db: Session, target_id: str) -> HealthCheck | None:
    return db.get(HealthCheck, target_id)


def save_config(db: Session, target_id: str, values: dict) -> HealthCheck:
    if db.get(Target, target_id) is None:
        raise ResourceNotFound("Target", target_id)
    cfg = db.get(HealthCheck, target_id)
    if cfg is None:
        cfg = HealthCheck(target_id=target_id, **values)
        db.add(cfg)
    else:
        for key, value in values.items():
            setattr(cfg, key, value)
    if not cfg.enabled:
        cfg.next_run_at = None
    elif cfg.next_run_at is None:
        cfg.next_run_at = datetime.now(UTC)
    db.commit()
    db.refresh(cfg)
    return cfg


def delete_config(db: Session, target_id: str) -> None:
    db.execute(delete(HealthCheck).where(HealthCheck.target_id == target_id))
    db.commit()


def recent_results(db: Session, target_id: str, limit: int = 20) -> list[HealthCheckResult]:
    return list(
        db.scalars(
            select(HealthCheckResult)
            .where(HealthCheckResult.target_id == target_id)
            .order_by(HealthCheckResult.started_at.desc())
            .limit(limit)
        ).all()
    )


# ------------------------------------------------------------------------------------- running


def _prepare(db: Session, target_id: str, trigger: str) -> _Prepared:
    cfg = db.get(HealthCheck, target_id)
    target = db.get(Target, target_id)
    if cfg is None or target is None:
        raise ResourceNotFound("Health check", target_id)
    if not target.enabled:
        raise _Skip("target is disabled")
    if target.status == "retired":
        raise _Skip("target is retired")
    if target.status == "maintenance" and not cfg.maintenance_by_check and trigger == "schedule":
        raise _Skip("target is in maintenance")

    now = datetime.now(UTC)
    reservations = ReservationRepository(db)
    reservations.expire_due(now)
    window_end = now + timedelta(seconds=cfg.boot_timeout_seconds + RESERVATION_MARGIN_SECONDS)
    reservations.lock_target(target_id)
    conflict = reservations.find_overlapping_active(target_id, now, window_end)
    if conflict is not None:
        db.rollback()
        raise _Skip(f"target is reserved by {conflict.user_id}")
    reservation = reservations.create(
        Reservation(
            id=str(uuid.uuid4()),
            target_id=target_id,
            user_id=HEALTH_USER,
            starts_at=now,
            ends_at=window_end,
            status="active",
            note="Automated health check",
        )
    )
    sessions = SessionService(SessionRepository(db), reservations, TargetRepository(db))
    try:
        serial = sessions.create_session(reservation.id, HEALTH_USER, "serial")
        power = sessions.create_session(reservation.id, HEALTH_USER, "power")
    except ConflictResource as exc:
        _end_reservation(db, reservation.id)
        raise _Skip(f"needs one enabled serial and one enabled power capability ({exc})") from exc
    return _Prepared(reservation.id, serial.id, power.id, cfg)


def _end_reservation(db: Session, reservation_id: str) -> None:
    reservations = ReservationRepository(db)
    reservation = reservations.get(reservation_id)
    if reservation is None or reservation.status != "active":
        return
    now = datetime.now(UTC)
    reservation.status = "released"
    reservation.released_at = now
    reservation.released_by = HEALTH_USER
    SessionRepository(db).close_active_for_reservation(reservation.id, now)
    reservations.update(reservation)


async def _boot_sequence(gateway, prepared: _Prepared) -> None:
    """Raises ConflictResource (or any error) when the board does not come up."""

    async def run(session_id: str, operation: str, params: dict | None = None) -> dict:
        return await gateway.execute_async(session_id, HEALTH_USER, operation, params or {})

    await run(prepared.serial_id, "open")
    await run(prepared.serial_id, "read", {"size": 65536, "wait_ms": 0})  # drop output from before the check
    await run(prepared.power_id, prepared.power_operation)

    deadline = time.monotonic() + prepared.timeout
    received = ""
    while prepared.pattern not in received:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            tail = " ".join(received[-120:].split())
            seen = f" Last output: {tail}" if tail else " No output was received."
            raise ConflictResource(
                f"Boot text '{prepared.pattern}' not seen within {prepared.timeout}s.{seen}"
            )
        result = await run(prepared.serial_id, "read", {"size": 65536, "wait_ms": int(min(remaining, 2) * 1000)})
        received += (result.get("data") or {}).get("data_text") or ""


def _record(db: Session, target_id: str, status: str, message: str, started: datetime, trigger: str) -> None:
    message = message[:500]
    now = datetime.now(UTC)
    db.add(
        HealthCheckResult(
            target_id=target_id,
            status=status,
            message=message,
            duration_seconds=round((now - started).total_seconds(), 2),
            trigger=trigger,
            started_at=started,
        )
    )
    db.commit()
    stale = db.scalars(
        select(HealthCheckResult.id)
        .where(HealthCheckResult.target_id == target_id)
        .order_by(HealthCheckResult.started_at.desc())
        .offset(RESULTS_KEPT_PER_TARGET)
    ).all()
    if stale:
        db.execute(delete(HealthCheckResult).where(HealthCheckResult.id.in_(stale)))
        db.commit()
    metrics.inc("targethub_health_checks_total", labels={"status": status})


def _apply_outcome(db: Session, target_id: str, status: str, message: str, trigger: str) -> str | None:
    """Update the check state and, when warranted, move the target in or out of maintenance.

    Returns the new target status when it changed.
    """
    cfg = db.get(HealthCheck, target_id)
    target = db.get(Target, target_id)
    if cfg is None or target is None:
        return None
    now = datetime.now(UTC)
    cfg.last_run_at = now
    cfg.last_status = status
    cfg.last_message = message[:500]
    if trigger == "schedule" and cfg.enabled:
        cfg.next_run_at = now + timedelta(minutes=cfg.interval_minutes)
    changed: str | None = None
    if status == "passed":
        cfg.consecutive_failures = 0
        if cfg.maintenance_by_check and target.status == "maintenance":
            target.status = "available"
            target.status_reason = None
            changed = "available"
        cfg.maintenance_by_check = False
    elif status == "failed":
        cfg.consecutive_failures += 1
        if (
            cfg.auto_maintenance
            and cfg.consecutive_failures >= cfg.failure_threshold
            and target.status == "available"
        ):
            target.status = "maintenance"
            target.status_reason = f"{MAINTENANCE_PREFIX}: {message}"[:500]
            cfg.maintenance_by_check = True
            changed = "maintenance"
    db.commit()
    if changed:
        reason = f" ({target.status_reason})" if target.status_reason else ""
        Notifier(db).event(
            "target.status",
            f"[{target.name}] is now {changed}{reason}",
            target_id=target.id,
            data={"target": target.name, "status": changed, "reason": target.status_reason, "source": "health-check"},
        )
    return changed


async def run_health_check(session_factory, target_id: str, trigger: str = "schedule") -> dict:
    """Run one check now. ``trigger`` is ``schedule`` or ``manual``. Returns status, message, duration."""
    from app.api.v1.sessions import build_gateway

    started = datetime.now(UTC)
    db = session_factory()
    prepared: _Prepared | None = None
    try:
        status, message = "passed", "Board booted and showed the expected text"
        try:
            prepared = await run_in_threadpool(_prepare, db, target_id, trigger)
        except _Skip as skip:
            status, message = "skipped", str(skip)
        if prepared is not None:
            gateway = build_gateway(db)
            try:
                await _boot_sequence(gateway, prepared)
            except Exception as exc:  # any failure to run the sequence means the board is not healthy
                status, message = "failed", str(getattr(exc, "detail", exc)) or exc.__class__.__name__
            finally:
                await run_in_threadpool(_end_reservation, db, prepared.reservation_id)
                for session_id in (prepared.serial_id, prepared.power_id):
                    gateway.release_session(session_id)

        def finish() -> None:
            _record(db, target_id, status, message, started, trigger)
            if status == "skipped":
                cfg = db.get(HealthCheck, target_id)
                if cfg is not None:
                    cfg.last_run_at = datetime.now(UTC)
                    cfg.last_status = "skipped"
                    cfg.last_message = message[:500]
                    if trigger == "schedule" and cfg.enabled:
                        # Try again soon rather than waiting a whole interval.
                        cfg.next_run_at = datetime.now(UTC) + timedelta(minutes=min(cfg.interval_minutes, 15))
                    db.commit()
            else:
                _apply_outcome(db, target_id, status, message, trigger)

        await run_in_threadpool(finish)
        return {"status": status, "message": message, "target_id": target_id}
    finally:
        db.close()


def claim_due(db: Session, now: datetime, limit: int = MAX_CHECKS_PER_TICK) -> list[str]:
    """Targets whose check is due; each is claimed (next_run_at pushed) so only one worker runs it."""
    due = db.scalars(
        select(HealthCheck.target_id)
        .where(HealthCheck.enabled.is_(True), HealthCheck.next_run_at.is_not(None), HealthCheck.next_run_at <= now)
        .order_by(HealthCheck.next_run_at.asc())
        .limit(limit)
    ).all()
    claimed: list[str] = []
    for target_id in due:
        cfg = db.get(HealthCheck, target_id)
        if cfg is None:
            continue
        lease = now + timedelta(seconds=cfg.boot_timeout_seconds + 2 * RESERVATION_MARGIN_SECONDS)
        won = db.execute(
            update(HealthCheck)
            .where(HealthCheck.target_id == target_id, HealthCheck.next_run_at <= now)
            .values(next_run_at=lease)
        ).rowcount
        db.commit()
        if won:
            claimed.append(target_id)
    return claimed


async def run_due_health_checks(session_factory) -> int:
    db = session_factory()
    try:
        due = await run_in_threadpool(claim_due, db, datetime.now(UTC))
    finally:
        db.close()
    for target_id in due:
        try:
            await run_health_check(session_factory, target_id, "schedule")
        except Exception as exc:
            logger.warning(f"health check for {target_id} crashed: {exc}")
    return len(due)


def purge_results(db: Session, now: datetime) -> int:
    result = db.execute(delete(HealthCheckResult).where(HealthCheckResult.started_at < now - RESULT_RETENTION))
    db.commit()
    return result.rowcount or 0
