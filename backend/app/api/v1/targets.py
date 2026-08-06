from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.dependencies import get_db
from app.repositories.target_repository import TargetRepository
from app.schemas.target import TargetCreate, TargetResponse, TargetUpdate
from app.services.target_service import TargetService

router = APIRouter(prefix="/targets", tags=["Targets"])


def get_service(db: Annotated[Session, Depends(get_db)]) -> TargetService:
    return TargetService(TargetRepository(db))


Service = Annotated[TargetService, Depends(get_service)]


@router.get("", response_model=list[TargetResponse])
def list_targets(service: Service):
    return service.list_targets()


@router.get("/{target_id}", response_model=TargetResponse)
def get_target(target_id: str, service: Service):
    return service.get_target(target_id)


@router.post("", response_model=TargetResponse, status_code=201)
def create_target(request: TargetCreate, service: Service):
    return service.create_target(**request.model_dump())


@router.put("/{target_id}", response_model=TargetResponse)
def update_target(
    target_id: str,
    request: TargetUpdate,
    service: Service,
):
    return service.update_target(
        target_id,
        **request.model_dump(exclude_unset=True),
    )


@router.delete("/{target_id}", status_code=204)
def delete_target(target_id: str, service: Service):
    service.delete_target(target_id)
