from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.api.dependencies import get_db
from app.core.config import settings
from app.repositories.agent_repository import AgentRepository
from app.schemas.agent import (
    AgentCreate,
    AgentEnrollRequest,
    AgentEnrollResponse,
    AgentEnrollmentCreate,
    AgentEnrollmentResponse,
    AgentHeartbeat,
    AgentResponse,
)
from app.services.agent_service import AgentService

router = APIRouter(prefix="/agents", tags=["Agents"])
bearer = HTTPBearer(auto_error=False)


def get_service(db: Annotated[Session, Depends(get_db)]) -> AgentService:
    return AgentService(AgentRepository(db))


Service = Annotated[AgentService, Depends(get_service)]
Credentials = Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]


@router.get("", response_model=list[AgentResponse])
def list_agents(service: Service):
    return service.list_agents()


@router.get("/enrollments", response_model=list[AgentEnrollmentResponse])
def list_enrollments(service: Service):
    return service.list_enrollments()


@router.post("/enrollments", response_model=AgentEnrollmentResponse, status_code=201)
def create_enrollment(request: AgentEnrollmentCreate, service: Service):
    enrollment, token = service.create_enrollment(request.agent_name, request.deployment_scenario)
    install_url = f"{settings.targethub_public_url.rstrip('/')}/web/agent/install.sh"
    return AgentEnrollmentResponse(
        id=enrollment.id,
        agent_name=enrollment.agent_name,
        deployment_scenario=enrollment.deployment_scenario,
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
    agent, credential = service.enroll(request.token, request.hostname, request.platform)
    return AgentEnrollResponse(
        agent=agent,
        credential=credential,
        heartbeat_url=f"{settings.targethub_public_url.rstrip('/')}/api/v1/agents/{agent.id}/heartbeat",
    )


@router.post("/register", response_model=AgentResponse, status_code=201, deprecated=True)
def register_agent(request: AgentCreate, service: Service):
    return service.register(request.name, request.hostname)


@router.post("/{agent_id}/heartbeat", response_model=AgentResponse)
def heartbeat(
    agent_id: str,
    request: AgentHeartbeat,
    credentials: Credentials,
    service: Service,
):
    if not credentials or credentials.scheme.lower() != "bearer":
        from fastapi import HTTPException

        raise HTTPException(status_code=401, detail="Agent credential required")
    agent = service.authenticate_credential(credentials.credentials)
    if agent.id != agent_id:
        from fastapi import HTTPException

        raise HTTPException(status_code=403, detail="Credential does not belong to this Agent")
    return service.heartbeat(agent, request.hostname, request.resources)


@router.post("/{agent_id}/disable", response_model=AgentResponse)
def disable_agent(agent_id: str, service: Service):
    return service.disable(agent_id)


@router.post("/{agent_id}/enable", response_model=AgentResponse)
def enable_agent(agent_id: str, service: Service):
    return service.enable(agent_id)


@router.post("/{agent_id}/revoke-credential", response_model=AgentResponse)
def revoke_credential(agent_id: str, service: Service):
    return service.revoke_credential(agent_id)


@router.get("/{agent_id}", response_model=AgentResponse)
def get_agent(agent_id: str, service: Service):
    return service.get_agent(agent_id)
