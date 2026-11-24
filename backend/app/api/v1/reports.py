"""Usage reports for lab owners (admin only): utilisation, idle reservations and waitlist times."""

import csv
import io
from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.api.dependencies import get_db, require_role
from app.services import report_service

router = APIRouter(prefix="/reports", tags=["Reports"])
DB = Annotated[Session, Depends(get_db)]

CSV_COLUMNS = {
    "targets": ["name", "tags", "reservations", "users", "booked_hours", "utilisation_percent", "idle_reservations", "idle_hours"],
    "tags": ["tag", "targets", "reservations", "booked_hours", "utilisation_percent"],
    "users": ["user_id", "reservations", "targets", "booked_hours", "idle_reservations", "idle_hours"],
    "idle": ["target", "user_id", "starts_at", "hours_held", "note"],
    "waitlist": ["user_id", "target", "tag", "status", "requested_at", "wait_minutes"],
}


def _period(start: datetime | None, end: datetime | None) -> tuple[datetime, datetime]:
    try:
        return report_service.resolve_period(start, end)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/usage")
def usage(
    db: DB,
    start: Annotated[datetime | None, Query(alias="from", description="ISO time; default: 30 days before 'to'")] = None,
    end: Annotated[datetime | None, Query(alias="to", description="ISO time; default: now")] = None,
    _admin=Depends(require_role("admin")),
) -> dict[str, Any]:
    start, end = _period(start, end)
    return report_service.usage_report(db, start, end)


@router.get("/usage.csv")
def usage_csv(
    db: DB,
    kind: Literal["targets", "tags", "users", "idle", "waitlist"] = "targets",
    start: Annotated[datetime | None, Query(alias="from")] = None,
    end: Annotated[datetime | None, Query(alias="to")] = None,
    _admin=Depends(require_role("admin")),
) -> Response:
    start, end = _period(start, end)
    if kind == "waitlist":
        rows = report_service.waitlist_entries(db, start, end)
    else:
        rows = report_service.usage_report(db, start, end)[kind]
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    columns = CSV_COLUMNS[kind]
    writer.writerow(columns)
    for row in rows:
        writer.writerow([_cell(row.get(column)) for column in columns])
    stamp = datetime.now(UTC).strftime("%Y%m%d")
    return Response(
        buffer.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="targethub-{kind}-{stamp}.csv"'},
    )


def _cell(value: Any) -> str:
    """Neutralise spreadsheet formulas in user-supplied text (notes, tags, names)."""
    if isinstance(value, list):
        value = ";".join(str(item) for item in value)
    text = "" if value is None else str(value)
    return "'" + text if text[:1] in ("=", "+", "-", "@", "\t", "\r") else text
