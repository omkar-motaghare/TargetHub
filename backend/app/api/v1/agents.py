from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.dependencies import get_db
from app.repositories.agent_repository import AgentRepository
from app.schemas.agent import AgentCreate, AgentHeartbeat, AgentResponse
from app.services.agent_service import AgentService

router = APIRouter(prefix="/agents", tags=["Agents"])


def get_service(db: Annotated[Session, Depends(get_db)]) -> AgentService:
    return AgentService(AgentRepository(db))


Service = Annotated[AgentService, Depends(get_service)]


@router.get("", response_model=list[AgentResponse])
def list_agents(service: Service):
    return service.list_agents()


@router.post("/register", response_model=AgentResponse, status_code=201)
def register_agent(request: AgentCreate, service: Service):
    return service.register(request.name, request.hostname)


@router.post("/{agent_id}/heartbeat", response_model=AgentResponse)
def heartbeat(agent_id: str, request: AgentHeartbeat, service: Service):
    return service.heartbeat(agent_id, request.hostname, request.resources)


@router.get("/{agent_id}", response_model=AgentResponse)
def get_agent(agent_id: str, service: Service):
    return service.get_agent(agent_id)
