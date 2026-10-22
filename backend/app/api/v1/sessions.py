from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.dependencies import (
    get_current_user,
    get_db,
    is_admin_user,
    resolve_effective_user_id,
)
from app.repositories.agent_operation_repository import AgentOperationRepository
from app.repositories.agent_repository import AgentRepository
from app.repositories.audit_repository import AuditRepository
from app.repositories.reservation_repository import ReservationRepository
from app.repositories.session_repository import SessionRepository
from app.repositories.target_repository import TargetRepository
from app.schemas.session import SessionCreate, SessionPublicResponse, SessionResponse
from app.services.agent_operation_service import AgentOperationService
from app.services.audit_service import AuditService
from app.services.provider_gateway import ProviderGateway
from app.services.session_service import SessionService

router = APIRouter(prefix="/sessions", tags=["Sessions"])


def get_audit_service(db: Annotated[Session, Depends(get_db)]) -> AuditService:
    return AuditService(AuditRepository(db))


AuditDep = Annotated[AuditService, Depends(get_audit_service)]


def get_service(db: Annotated[Session, Depends(get_db)]) -> SessionService:
    return SessionService(
        SessionRepository(db),
        ReservationRepository(db),
        TargetRepository(db),
    )


Service = Annotated[SessionService, Depends(get_service)]


def get_provider_gateway(db: Annotated[Session, Depends(get_db)]) -> ProviderGateway:
    return ProviderGateway(
        SessionRepository(db),
        AuditService(AuditRepository(db)),
        TargetRepository(db),
        AgentOperationService(
            AgentOperationRepository(db),
            SessionRepository(db),
            AgentRepository(db),
        ),
    )


Gateway = Annotated[ProviderGateway, Depends(get_provider_gateway)]


def present(session, user) -> SessionResponse | SessionPublicResponse:
    if is_admin_user(user):
        return SessionResponse.model_validate(session)
    return SessionPublicResponse.model_validate(session)


def scrub(result: dict[str, Any], user) -> dict[str, Any]:
    if is_admin_user(user):
        return result
    return {key: value for key, value in result.items() if key != "provider_key"}


class SerialWriteRequest(BaseModel):
    text: str = Field(default="")


class ExecuteRequest(BaseModel):
    operation: str = Field(min_length=1, max_length=64)
    params: dict[str, Any] = Field(default_factory=dict)


@router.get("", response_model=list[SessionResponse | SessionPublicResponse])
def list_sessions(
    service: Service,
    user_id: str | None = Query(default=None),
    target_id: str | None = Query(default=None),
    user=Depends(get_current_user),
):
    if not is_admin_user(user):
        user_id = user.username
    elif user_id:
        user_id = resolve_effective_user_id(user, user_id)
    return [present(item, user) for item in service.list_sessions(user_id=user_id, target_id=target_id)]


@router.get("/{session_id}", response_model=SessionResponse | SessionPublicResponse, responses={403: {"description": "Forbidden"}})
def get_session(
    session_id: str,
    service: Service,
    user=Depends(get_current_user),
):
    session = service.get_session(session_id)
    if session.user_id != user.username and not is_admin_user(user):
        from fastapi import HTTPException

        raise HTTPException(status_code=403, detail="forbidden")
    return present(session, user)


@router.post("", response_model=SessionResponse | SessionPublicResponse, status_code=201)
def create_session(
    request: SessionCreate,
    service: Service,
    audit: AuditDep,
    user=Depends(get_current_user),
):
    payload = request.model_dump()
    payload["user_id"] = resolve_effective_user_id(user, payload.get("user_id"))
    session = service.create_session(**payload)
    audit.record(
        action="session.open",
        user_id=session.user_id,
        target_id=session.target_id,
        session_id=session.id,
        provider_key=session.provider_key,
        capability_type=session.capability_type,
    )
    return present(session, user)


@router.post("/{session_id}/close", response_model=SessionResponse | SessionPublicResponse)
def close_session(
    session_id: str,
    service: Service,
    gateway: Gateway,
    audit: AuditDep,
    user_id: str | None = Query(default=None, min_length=1),
    user=Depends(get_current_user),
):
    effective_user_id = resolve_effective_user_id(user, user_id)
    session = service.close_session(session_id, effective_user_id)
    gateway.release_session(session_id)
    audit.record(
        action="session.close",
        user_id=session.user_id,
        target_id=session.target_id,
        session_id=session.id,
        capability_type=session.capability_type,
    )
    return present(session, user)


@router.get("/{session_id}/operations")
def session_operations(
    session_id: str,
    gateway: Gateway,
    user=Depends(get_current_user),
):
    return scrub(gateway.operations_for(session_id, user.username), user)


@router.post("/{session_id}/execute")
def session_execute(
    session_id: str,
    request: ExecuteRequest,
    gateway: Gateway,
    user=Depends(get_current_user),
):
    return scrub(gateway.execute(session_id, user.username, request.operation, request.params), user)


@router.post("/{session_id}/serial/open")
def serial_open(
    session_id: str,
    gateway: Gateway,
    user=Depends(get_current_user),
):
    return scrub(gateway.serial_open(session_id, user.username), user)


@router.get("/{session_id}/serial/read")
def serial_read(
    session_id: str,
    gateway: Gateway,
    size: int = Query(default=4096, ge=1, le=65536),
    user=Depends(get_current_user),
):
    return scrub(gateway.serial_read(session_id, user.username, size=size), user)


@router.post("/{session_id}/serial/write")
def serial_write(
    session_id: str,
    request: SerialWriteRequest,
    gateway: Gateway,
    user=Depends(get_current_user),
):
    return scrub(gateway.serial_write(session_id, user.username, text=request.text), user)


@router.post("/{session_id}/serial/close")
def serial_close(
    session_id: str,
    gateway: Gateway,
    user=Depends(get_current_user),
):
    return scrub(gateway.serial_close(session_id, user.username), user)
