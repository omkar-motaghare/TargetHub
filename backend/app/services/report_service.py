"""Usage reports: how much each board is booked, who holds boards without using them, how long people wait."""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.lab import WaitlistEntry
from app.models.reservation import Reservation
from app.models.session import TargetSession
from app.models.target import Target
from app.models.team import Team, TeamMember
from app.services.health_check_service import HEALTH_USER

MAX_SPAN_DAYS = 366
IDLE_ROWS = 100


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _hours(seconds: float) -> float:
    return round(seconds / 3600, 2)


def resolve_period(start: datetime | None, end: datetime | None, now: datetime | None = None) -> tuple[datetime, datetime]:
    now = now or datetime.now(UTC)
    end = _utc(end) if end else now
    start = _utc(start) if start else end - timedelta(days=30)
    if start >= end:
        raise ValueError("'from' must be before 'to'")
    if end - start > timedelta(days=MAX_SPAN_DAYS):
        raise ValueError(f"the period may not exceed {MAX_SPAN_DAYS} days")
    return start, end


def _effective_window(reservation: Reservation, now: datetime) -> tuple[datetime, datetime]:
    """The time a reservation actually held the board: until release, expiry, or now if still running."""
    starts = _utc(reservation.starts_at)
    ends = _utc(reservation.ends_at)
    if reservation.released_at is not None:
        ends = min(ends, _utc(reservation.released_at))
    elif reservation.status == "active":
        ends = min(ends, now)
    return starts, max(starts, ends)


def _overlap_seconds(window: tuple[datetime, datetime], start: datetime, end: datetime) -> float:
    return max(0.0, (min(window[1], end) - max(window[0], start)).total_seconds())


def usage_report(db: Session, start: datetime, end: datetime, now: datetime | None = None) -> dict[str, Any]:
    """Aggregate bookings in ``[start, end)``. Automated health checks are not counted as usage."""
    now = now or datetime.now(UTC)
    end = min(end, now)
    period_seconds = max((end - start).total_seconds(), 1.0)

    targets = {t.id: t for t in db.scalars(select(Target)).all()}
    reservations = [
        r
        for r in db.scalars(
            select(Reservation).where(
                Reservation.user_id != HEALTH_USER,
                Reservation.starts_at < end,
                Reservation.ends_at > start,
            )
        ).all()
        if r.status != "cancelled"
    ]
    with_sessions = set(
        db.scalars(
            select(TargetSession.reservation_id).where(
                TargetSession.reservation_id.in_([r.id for r in reservations] or [""])
            )
        ).all()
    )

    per_target: dict[str, dict[str, Any]] = {}
    per_user: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"reservations": 0, "booked_seconds": 0.0, "idle_reservations": 0, "idle_seconds": 0.0, "targets": set()}
    )
    idle_rows: list[dict[str, Any]] = []
    for reservation in reservations:
        window = _effective_window(reservation, now)
        seconds = _overlap_seconds(window, start, end)
        if seconds <= 0:
            continue
        # An idle reservation is one that has run (at least in part) without any session ever opened.
        idle = reservation.id not in with_sessions and window[1] > window[0] and _utc(reservation.starts_at) < now
        target = targets.get(reservation.target_id)
        row = per_target.setdefault(
            reservation.target_id,
            {"reservations": 0, "booked_seconds": 0.0, "idle_reservations": 0, "idle_seconds": 0.0, "users": set()},
        )
        user = per_user[reservation.user_id]
        for bucket in (row, user):
            bucket["reservations"] += 1
            bucket["booked_seconds"] += seconds
        row["users"].add(reservation.user_id)
        user["targets"].add(reservation.target_id)
        if idle:
            for bucket in (row, user):
                bucket["idle_reservations"] += 1
                bucket["idle_seconds"] += seconds
            idle_rows.append(
                {
                    "reservation_id": reservation.id,
                    "target": target.name if target else reservation.target_id,
                    "user_id": reservation.user_id,
                    "starts_at": _utc(reservation.starts_at).isoformat(),
                    "hours_held": _hours(seconds),
                    "note": reservation.note,
                }
            )

    target_rows = []
    for target_id, target in sorted(targets.items(), key=lambda item: item[1].name.lower()):
        if target.status == "retired" and target_id not in per_target:
            continue
        data = per_target.get(target_id)
        booked = data["booked_seconds"] if data else 0.0
        target_rows.append(
            {
                "target_id": target_id,
                "name": target.name,
                "tags": list(target.tags or []),
                "reservations": data["reservations"] if data else 0,
                "users": len(data["users"]) if data else 0,
                "booked_hours": _hours(booked),
                "utilisation_percent": round(min(100.0, booked / period_seconds * 100), 1),
                "idle_reservations": data["idle_reservations"] if data else 0,
                "idle_hours": _hours(data["idle_seconds"]) if data else 0.0,
            }
        )

    tag_rows = []
    by_tag: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in target_rows:
        for tag in row["tags"]:
            by_tag[tag].append(row)
    for tag, rows in sorted(by_tag.items()):
        booked = sum(item["booked_hours"] for item in rows)
        tag_rows.append(
            {
                "tag": tag,
                "targets": len(rows),
                "reservations": sum(item["reservations"] for item in rows),
                "booked_hours": round(booked, 2),
                "utilisation_percent": round(min(100.0, booked * 3600 / (period_seconds * len(rows)) * 100), 1),
            }
        )

    user_rows = sorted(
        (
            {
                "user_id": user_id,
                "reservations": data["reservations"],
                "targets": len(data["targets"]),
                "booked_hours": _hours(data["booked_seconds"]),
                "idle_reservations": data["idle_reservations"],
                "idle_hours": _hours(data["idle_seconds"]),
            }
            for user_id, data in per_user.items()
        ),
        key=lambda item: -item["booked_hours"],
    )
    idle_rows.sort(key=lambda item: -item["hours_held"])

    members_by_team: dict[str, set[str]] = {name: set() for name in db.scalars(select(Team.name)).all()}
    for team_name, username in db.execute(
        select(Team.name, TeamMember.username).join(TeamMember, TeamMember.team_id == Team.id)
    ).all():
        members_by_team[team_name].add(username)
    team_rows = []
    for team_name, members in sorted(members_by_team.items()):
        used = [per_user[name] for name in members if name in per_user]
        team_rows.append(
            {
                "team": team_name,
                "members": len(members),
                "active_users": len(used),
                "reservations": sum(item["reservations"] for item in used),
                "booked_hours": _hours(sum(item["booked_seconds"] for item in used)),
                "idle_hours": _hours(sum(item["idle_seconds"] for item in used)),
            }
        )
    team_rows.sort(key=lambda item: -item["booked_hours"])

    total_booked = sum(item["booked_hours"] for item in target_rows)
    total_idle = sum(item["idle_hours"] for item in target_rows)
    return {
        "period": {"from": start.isoformat(), "to": end.isoformat(), "hours": _hours(period_seconds)},
        "totals": {
            "targets": len(target_rows),
            "reservations": sum(item["reservations"] for item in target_rows),
            "users": len(user_rows),
            "booked_hours": round(total_booked, 2),
            "idle_reservations": sum(item["idle_reservations"] for item in target_rows),
            "idle_hours": round(total_idle, 2),
            "idle_share_percent": round(total_idle / total_booked * 100, 1) if total_booked else 0.0,
        },
        "targets": target_rows,
        "tags": tag_rows,
        "users": user_rows,
        "teams": team_rows,
        "idle": idle_rows[:IDLE_ROWS],
        "waitlist": waitlist_summary(db, start, end, targets),
    }


def waitlist_entries(db: Session, start: datetime, end: datetime, targets: dict[str, Target] | None = None) -> list[dict[str, Any]]:
    targets = targets if targets is not None else {t.id: t for t in db.scalars(select(Target)).all()}
    entries = db.scalars(
        select(WaitlistEntry)
        .where(WaitlistEntry.created_at >= start, WaitlistEntry.created_at < end)
        .order_by(WaitlistEntry.created_at.asc())
    ).all()
    rows = []
    for entry in entries:
        wait = None
        if entry.fulfilled_at is not None:
            wait = round((_utc(entry.fulfilled_at) - _utc(entry.created_at)).total_seconds() / 60, 1)
        target = targets.get(entry.target_id) if entry.target_id else None
        rows.append(
            {
                "user_id": entry.user_id,
                "target": target.name if target else None,
                "tag": entry.tag,
                "status": entry.status,
                "requested_at": _utc(entry.created_at).isoformat(),
                "wait_minutes": wait,
            }
        )
    return rows


def waitlist_summary(db: Session, start: datetime, end: datetime, targets: dict[str, Target]) -> dict[str, Any]:
    rows = waitlist_entries(db, start, end, targets)
    waits = [row["wait_minutes"] for row in rows if row["wait_minutes"] is not None]
    count = {status: sum(1 for row in rows if row["status"] == status) for status in ("fulfilled", "waiting", "cancelled", "expired")}
    return {
        "entries": len(rows),
        **count,
        "average_wait_minutes": round(sum(waits) / len(waits), 1) if waits else None,
        "longest_wait_minutes": max(waits) if waits else None,
    }
