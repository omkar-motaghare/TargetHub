from typing import Annotated

from fastapi import APIRouter, Depends, Query
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
from app.schemas.reservation import ReservationCreate, ReservationResponse
from app.services.audit_service import AuditService
from app.services.reservation_service import ReservationService

router = APIRouter(prefix="/reservations", tags=["Reservations"])


def get_service(db: Annotated[Session, Depends(get_db)]) -> ReservationService:
    return ReservationService(
        ReservationRepository(db),
        TargetRepository(db),
        SessionRepository(db),
    )


Service = Annotated[ReservationService, Depends(get_service)]


def get_audit_service(db: Annotated[Session, Depends(get_db)]) -> AuditService:
    return AuditService(AuditRepository(db))


AuditDep = Annotated[AuditService, Depends(get_audit_service)]


@router.get("", response_model=list[ReservationResponse])
def list_reservations(
    service: Service,
    target_id: str | None = Query(default=None),
    user_id: str | None = Query(default=None),
    user=Depends(get_current_user),
):
    if not is_admin_user(user):
        user_id = user.username
    elif user_id:
        user_id = resolve_effective_user_id(user, user_id)
    return service.list_reservations(target_id=target_id, user_id=user_id)


@router.get("/{reservation_id}", response_model=ReservationResponse)
def get_reservation(
    reservation_id: str,
    service: Service,
    user=Depends(get_current_user),
):
    reservation = service.get_reservation(reservation_id)
    if reservation.user_id != user.username and not is_admin_user(user):
        from fastapi import HTTPException

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
    reservation = service.create_reservation(**payload)
    audit.record(
        action="reservation.create",
        user_id=reservation.user_id,
        target_id=reservation.target_id,
        detail=f"reservation {reservation.id}",
    )
    return reservation


@router.post("/{reservation_id}/release", response_model=ReservationResponse)
def release_reservation(
    reservation_id: str,
    service: Service,
    audit: AuditDep,
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
    return reservation


@router.post("/{reservation_id}/force-release", response_model=ReservationResponse)
def force_release_reservation(
    reservation_id: str,
    service: Service,
    audit: AuditDep,
    admin=Depends(require_role("admin")),
):
    reservation = service.force_release_reservation(reservation_id)
    audit.record(
        action="reservation.force_release",
        user_id=admin.username,
        target_id=reservation.target_id,
        detail=f"reservation {reservation.id}",
    )
    return reservation
