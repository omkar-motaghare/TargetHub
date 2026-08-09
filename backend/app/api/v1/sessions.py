from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.dependencies import get_db
from app.repositories.reservation_repository import ReservationRepository
from app.repositories.session_repository import SessionRepository
from app.repositories.target_repository import TargetRepository
from app.schemas.session import SessionCreate, SessionResponse
from app.services.session_service import SessionService

router = APIRouter(prefix="/sessions", tags=["Sessions"])


def get_service(db: Annotated[Session, Depends(get_db)]) -> SessionService:
    return SessionService(
        SessionRepository(db),
        ReservationRepository(db),
        TargetRepository(db),
    )


Service = Annotated[SessionService, Depends(get_service)]


@router.get("", response_model=list[SessionResponse])
def list_sessions(
    service: Service,
    user_id: str | None = Query(default=None),
    target_id: str | None = Query(default=None),
):
    return service.list_sessions(user_id=user_id, target_id=target_id)


@router.get("/{session_id}", response_model=SessionResponse)
def get_session(session_id: str, service: Service):
    return service.get_session(session_id)


@router.post("", response_model=SessionResponse, status_code=201)
def create_session(request: SessionCreate, service: Service):
    return service.create_session(**request.model_dump())


@router.post("/{session_id}/close", response_model=SessionResponse)
def close_session(
    session_id: str,
    service: Service,
    user_id: str = Query(..., min_length=1),
):
    return service.close_session(session_id, user_id)
