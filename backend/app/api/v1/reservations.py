from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.dependencies import (
    get_current_user,
    get_db,
    is_admin_user,
    require_operator,
    require_role,
    resolve_effective_user_id,
)
from app.repositories.audit_repository import AuditRepository
from app.repositories.reservation_repository import ReservationRepository
from app.repositories.session_repository import SessionRepository
from app.repositories.target_repository import TargetRepository
from app.schemas.reservation import (
    ExtendRequest,
    ReservationCreate,
    ReservationResponse,
    ReserveAnyRequest,
)
from app.services.audit_service import AuditService
from app.services.lab_settings import LabSettings
from app.services.notifier import Notifier
from app.services.reservation_service import ReservationService
from app.services.waitlist_service import WaitlistService

router = APIRouter(prefix="/reservations", tags=["Reservations"])

MAX_CALENDAR_DAYS = 62


def get_service(db: Annotated[Session, Depends(get_db)]) -> ReservationService:
    return ReservationService(
        ReservationRepository(db),
        TargetRepository(db),
        SessionRepository(db),
        policy=LabSettings(db).policy(),
        notifier=Notifier(db),
    )


Service = Annotated[ReservationService, Depends(get_service)]


def get_audit_service(db: Annotated[Session, Depends(get_db)]) -> AuditService:
    return AuditService(AuditRepository(db))


AuditDep = Annotated[AuditService, Depends(get_audit_service)]
DB = Annotated[Session, Depends(get_db)]


def _utc(value: datetime) -> datetime:
    return value.astimezone(UTC) if value.tzinfo else value.replace(tzinfo=UTC)


def _process_waitlist(db: Session) -> None:
    """A target just became free: give it to the next person waiting."""
    WaitlistService(db).process()


@router.get("", response_model=list[ReservationResponse])
def list_reservations(
    service: Service,
    target_id: str | None = Query(default=None),
    user_id: str | None = Query(default=None),
    status: str | None = Query(default=None, pattern="^(active|released|expired)$"),
    user=Depends(get_current_user),
):
    """Your reservations (admins: everyone's, optionally filtered by user)."""
    if not is_admin_user(user):
        user_id = user.username
    elif user_id:
        user_id = resolve_effective_user_id(user, user_id)
    return service.list_reservations(target_id=target_id, user_id=user_id, status=status)


@router.get("/calendar", response_model=list[ReservationResponse])
def reservation_calendar(
    service: Service,
    start: datetime | None = Query(default=None, alias="from"),
    end: datetime | None = Query(default=None, alias="to"),
    target_id: str | None = Query(default=None),
    _user=Depends(get_current_user),
):
    """Every active reservation overlapping a window (default: next 7 days), for all users.

    Who has which board, and when, is shared lab information; it is what
    prevents people from coordinating through chat.
    """
    now = datetime.now(UTC)
    start = _utc(start) if start else now - timedelta(hours=12)
    end = _utc(end) if end else start + timedelta(days=7)
    if end <= start:
        raise HTTPException(status_code=422, detail="'to' must be after 'from'")
    if end - start > timedelta(days=MAX_CALENDAR_DAYS):
        raise HTTPException(status_code=422, detail=f"Calendar window is limited to {MAX_CALENDAR_DAYS} days")
    return service.list_reservations(
        target_id=target_id, status="active", starts_before=end, ends_after=start
    )


@router.get("/{reservation_id}", response_model=ReservationResponse)
def get_reservation(
    reservation_id: str,
    service: Service,
    user=Depends(get_current_user),
):
    reservation = service.get_reservation(reservation_id)
    if reservation.user_id != user.username and not is_admin_user(user):
        raise HTTPException(status_code=403, detail="forbidden")
    return reservation


@router.post("", response_model=ReservationResponse, status_code=201)
def create_reservation(
    request: ReservationCreate,
    service: Service,
    audit: AuditDep,
    user=Depends(require_operator),
):
    payload = request.model_dump()
    payload["user_id"] = resolve_effective_user_id(user, payload.get("user_id"))
    reservation = service.create_reservation(**payload, privileged=is_admin_user(user))
    audit.record(
        action="reservation.create",
        user_id=reservation.user_id,
        target_id=reservation.target_id,
        detail=f"reservation {reservation.id}" + (f" by {user.username}" if user.username != reservation.user_id else ""),
    )
    return reservation


@router.post("/any", response_model=ReservationResponse, status_code=201)
def reserve_any(
    request: ReserveAnyRequest,
    service: Service,
    audit: AuditDep,
    user=Depends(require_operator),
):
    """Reserve whichever free target carries ``tag`` (e.g. "stm32-nucleo")."""
    reservation = service.reserve_any(
        request.tag.strip().lower(),
        user.username,
        request.duration_minutes,
        request.starts_at,
        request.note,
        privileged=is_admin_user(user),
    )
    audit.record(
        action="reservation.create",
        user_id=reservation.user_id,
        target_id=reservation.target_id,
        detail=f"reservation {reservation.id} via tag '{request.tag}'",
    )
    return reservation


@router.post("/{reservation_id}/extend", response_model=ReservationResponse)
def extend_reservation(
    reservation_id: str,
    request: ExtendRequest,
    service: Service,
    audit: AuditDep,
    user=Depends(require_operator),
):
    if (request.ends_at is None) == (request.extend_minutes is None):
        raise HTTPException(status_code=422, detail="Provide exactly one of ends_at or extend_minutes")
    if request.ends_at is not None:
        ends_at = request.ends_at
    else:
        current = service.get_reservation(reservation_id)
        ends_at = _utc(current.ends_at) + timedelta(minutes=request.extend_minutes)
    reservation = service.extend_reservation(
        reservation_id, user.username, ends_at, privileged=is_admin_user(user)
    )
    audit.record(
        action="reservation.extend",
        user_id=user.username,
        target_id=reservation.target_id,
        detail=f"reservation {reservation.id} until {ends_at.isoformat()}",
    )
    return reservation


@router.post("/{reservation_id}/release", response_model=ReservationResponse)
def release_reservation(
    reservation_id: str,
    service: Service,
    audit: AuditDep,
    db: DB,
    user_id: str | None = Query(default=None, min_length=1),
    user=Depends(get_current_user),
):
    effective_user_id = resolve_effective_user_id(user, user_id)
    reservation = service.release_reservation(reservation_id, effective_user_id)
    audit.record(
        action="reservation.release",
        user_id=effective_user_id,
        target_id=reservation.target_id,
        detail=f"reservation {reservation.id}",
    )
    _process_waitlist(db)
    return reservation


@router.post("/{reservation_id}/force-release", response_model=ReservationResponse)
def force_release_reservation(
    reservation_id: str,
    service: Service,
    audit: AuditDep,
    db: DB,
    admin=Depends(require_role("admin")),
):
    reservation = service.force_release_reservation(reservation_id, actor=admin.username)
    audit.record(
        action="reservation.force_release",
        user_id=admin.username,
        target_id=reservation.target_id,
        detail=f"reservation {reservation.id} of {reservation.user_id}",
    )
    _process_waitlist(db)
    return reservation
