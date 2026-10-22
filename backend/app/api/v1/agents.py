from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.api.dependencies import get_db, require_role
from app.core.config import settings
from app.repositories.agent_operation_repository import AgentOperationRepository
from app.repositories.agent_repository import AgentRepository
from app.repositories.session_repository import SessionRepository
from app.schemas.agent import (
    AgentCreate,
    AgentEnrollmentCreate,
    AgentEnrollmentResponse,
    AgentEnrollRequest,
    AgentEnrollResponse,
    AgentHeartbeat,
    AgentOperationCompleteRequest,
    AgentOperationCompleteResponse,
    AgentOperationPayload,
    AgentOperationPollRequest,
    AgentOperationPollResponse,
    AgentResponse,
)
from app.services.agent_operation_service import AgentOperationService
from app.services.agent_service import AgentService

router = APIRouter(prefix="/agents", tags=["Agents"])
bearer = HTTPBearer(auto_error=False)


def get_service(db: Annotated[Session, Depends(get_db)]) -> AgentService:
    return AgentService(AgentRepository(db))


Service = Annotated[AgentService, Depends(get_service)]
Credentials = Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]


def get_operation_service(db: Annotated[Session, Depends(get_db)]) -> AgentOperationService:
    return AgentOperationService(
        AgentOperationRepository(db),
        SessionRepository(db),
        AgentRepository(db),
    )


OperationService = Annotated[AgentOperationService, Depends(get_operation_service)]


def _authenticate_agent(agent_id: str, credentials: Credentials, service: Service):
    if not credentials or credentials.scheme.lower() != "bearer":
        raise HTTPException(status_code=401, detail="Agent credential required")
    agent = service.authenticate_credential(credentials.credentials)
    if agent.id != agent_id:
        raise HTTPException(status_code=403, detail="Credential does not belong to this Agent")
    return agent


@router.get("", response_model=list[AgentResponse])
def list_agents(service: Service, _admin=Depends(require_role("admin"))):
    return service.list_agents()


@router.get("/enrollments", response_model=list[AgentEnrollmentResponse])
def list_enrollments(service: Service, _admin=Depends(require_role("admin"))):
    return service.list_enrollments()


@router.post("/enrollments", response_model=AgentEnrollmentResponse, status_code=201)
def create_enrollment(request: AgentEnrollmentCreate, service: Service, _admin=Depends(require_role("admin"))):
    enrollment, token = service.create_enrollment(request.agent_name)
    install_url = f"{settings.targethub_public_url.rstrip('/')}/web/agent/install.sh"
    return AgentEnrollmentResponse(
        id=enrollment.id,
        agent_name=enrollment.agent_name,
        expires_at=enrollment.expires_at,
        used_at=enrollment.used_at,
        agent_id=enrollment.agent_id,
        created_at=enrollment.created_at,
        token=token,
        targethub_url=settings.targethub_public_url.rstrip("/"),
        install_command=(
            f"curl -fsSL {install_url} | sudo bash -s -- "
            f"--targethub-url '{settings.targethub_public_url.rstrip('/')}' --enrollment-token '{token}'"
        ),
    )


@router.post("/enroll", response_model=AgentEnrollResponse)
def enroll_agent(request: AgentEnrollRequest, service: Service):
    # Public by design: an Agent has no user account and authenticates with a
    # short-lived, single-use enrollment token instead of a TargetHub user token.
    agent, credential = service.enroll(request.token, request.hostname)
    return AgentEnrollResponse(
        agent=agent,
        credential=credential,
        heartbeat_url=f"{settings.targethub_public_url.rstrip('/')}/api/v1/agents/{agent.id}/heartbeat",
    )


@router.post("/register", response_model=AgentResponse, status_code=201, deprecated=True)
def register_agent(request: AgentCreate, service: Service, _admin=Depends(require_role("admin"))):
    return service.register(request.name, request.hostname)


@router.post("/{agent_id}/heartbeat", response_model=AgentResponse)
def heartbeat(
    agent_id: str,
    request: AgentHeartbeat,
    credentials: Credentials,
    service: Service,
):
    agent = _authenticate_agent(agent_id, credentials, service)
    return service.heartbeat(agent, request.hostname, request.resources)


@router.post("/{agent_id}/operations/poll", response_model=AgentOperationPollResponse)
def poll_agent_operation(
    agent_id: str,
    request: AgentOperationPollRequest,
    credentials: Credentials,
    service: Service,
    operations: OperationService,
):
    _authenticate_agent(agent_id, credentials, service)
    operation = operations.poll_for_agent(
        agent_id=agent_id,
        wait_seconds=request.wait_seconds,
        lease_seconds=request.lease_seconds,
    )
    if operation is None:
        return AgentOperationPollResponse(operation=None)
    return AgentOperationPollResponse(
        operation=AgentOperationPayload(
            id=operation.id,
            session_id=operation.session_id,
            resource_id=operation.resource_id,
            resource_key=operation.resource_key,
            resource_type=operation.resource_type,
            resource_metadata=operation.resource_metadata,
            operation=operation.operation,
            params=operation.params,
            requested_at=operation.requested_at,
        )
    )


@router.post(
    "/{agent_id}/operations/{operation_id}/complete",
    response_model=AgentOperationCompleteResponse,
)
def complete_agent_operation(
    agent_id: str,
    operation_id: str,
    request: AgentOperationCompleteRequest,
    credentials: Credentials,
    service: Service,
    operations: OperationService,
):
    _authenticate_agent(agent_id, credentials, service)
    updated = operations.complete_for_agent(
        agent_id=agent_id,
        operation_id=operation_id,
        success=request.success,
        message=request.message,
        data=request.data,
    )
    return AgentOperationCompleteResponse(status=updated.status, operation_id=updated.id)


@router.post("/{agent_id}/disable", response_model=AgentResponse)
def disable_agent(agent_id: str, service: Service, _admin=Depends(require_role("admin"))):
    return service.disable(agent_id)


@router.post("/{agent_id}/enable", response_model=AgentResponse)
def enable_agent(agent_id: str, service: Service, _admin=Depends(require_role("admin"))):
    return service.enable(agent_id)


@router.post("/{agent_id}/revoke-credential", response_model=AgentResponse)
def revoke_credential(agent_id: str, service: Service, _admin=Depends(require_role("admin"))):
    return service.revoke_credential(agent_id)


@router.get("/{agent_id}", response_model=AgentResponse)
def get_agent(agent_id: str, service: Service, _admin=Depends(require_role("admin"))):
    return service.get_agent(agent_id)
