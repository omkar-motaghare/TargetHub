from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user, get_db, require_role
from app.repositories.agent_repository import AgentRepository
from app.repositories.target_capability_repository import TargetCapabilityRepository
from app.repositories.target_repository import TargetRepository
from app.schemas.target_capability import (
    TargetCapabilityCreate,
    TargetCapabilityResponse,
    TargetCapabilityUpdate,
)
from app.services.target_capability_service import TargetCapabilityService

router = APIRouter(
    prefix="/targets/{target_id}/capabilities",
    tags=["Target Capabilities"],
)


def get_service(db: Annotated[Session, Depends(get_db)]) -> TargetCapabilityService:
    return TargetCapabilityService(
        TargetCapabilityRepository(db),
        TargetRepository(db),
        AgentRepository(db),
    )


Service = Annotated[TargetCapabilityService, Depends(get_service)]


@router.get("", response_model=list[TargetCapabilityResponse])
def list_capabilities(target_id: str, service: Service, _user=Depends(get_current_user)):
    return service.list_capabilities(target_id)


@router.get("/{capability_id}", response_model=TargetCapabilityResponse)
def get_capability(
    target_id: str,
    capability_id: str,
    service: Service,
    _user=Depends(get_current_user),
):
    return service.get_capability(target_id, capability_id)


@router.post("", response_model=TargetCapabilityResponse, status_code=201)
def create_capability(
    target_id: str,
    request: TargetCapabilityCreate,
    service: Service,
    _admin=Depends(require_role("admin")),
):
    return service.create_capability(target_id, **request.model_dump())


@router.put("/{capability_id}", response_model=TargetCapabilityResponse)
def update_capability(
    target_id: str,
    capability_id: str,
    request: TargetCapabilityUpdate,
    service: Service,
    _admin=Depends(require_role("admin")),
):
    return service.update_capability(
        target_id,
        capability_id,
        **request.model_dump(exclude_unset=True),
    )


@router.delete("/{capability_id}", status_code=204)
def delete_capability(
    target_id: str,
    capability_id: str,
    service: Service,
    _admin=Depends(require_role("admin")),
):
    service.delete_capability(target_id, capability_id)
