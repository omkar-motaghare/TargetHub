from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.dependencies import get_db
from app.repositories.reservation_repository import ReservationRepository
from app.repositories.target_repository import TargetRepository
from app.schemas.reservation import ReservationCreate, ReservationResponse
from app.services.reservation_service import ReservationService

router = APIRouter(prefix="/reservations", tags=["Reservations"])


def get_service(db: Annotated[Session, Depends(get_db)]) -> ReservationService:
    return ReservationService(
        ReservationRepository(db),
        TargetRepository(db),
    )


Service = Annotated[ReservationService, Depends(get_service)]


@router.get("", response_model=list[ReservationResponse])
def list_reservations(
    service: Service,
    target_id: str | None = Query(default=None),
    user_id: str | None = Query(default=None),
):
    return service.list_reservations(target_id=target_id, user_id=user_id)


@router.get("/{reservation_id}", response_model=ReservationResponse)
def get_reservation(reservation_id: str, service: Service):
    return service.get_reservation(reservation_id)


@router.post("", response_model=ReservationResponse, status_code=201)
def create_reservation(request: ReservationCreate, service: Service):
    return service.create_reservation(**request.model_dump())


@router.post("/{reservation_id}/release", response_model=ReservationResponse)
def release_reservation(
    reservation_id: str,
    service: Service,
    user_id: str = Query(..., min_length=1),
):
    return service.release_reservation(reservation_id, user_id)
