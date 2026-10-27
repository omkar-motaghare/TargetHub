from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user, get_db, is_admin_user, require_role
from app.repositories.agent_repository import AgentRepository
from app.repositories.audit_repository import AuditRepository
from app.repositories.reservation_repository import ReservationRepository
from app.repositories.target_repository import TargetRepository
from app.schemas.target import (
    Availability,
    TargetCreate,
    TargetPublicResponse,
    TargetResponse,
    TargetUpdate,
)
from app.services.audit_service import AuditService
from app.services.notifier import Notifier
from app.services.reservation_service import availability
from app.services.target_service import TargetService

router = APIRouter(prefix="/targets", tags=["Targets"])


def get_service(db: Annotated[Session, Depends(get_db)]) -> TargetService:
    return TargetService(TargetRepository(db), AgentRepository(db))


Service = Annotated[TargetService, Depends(get_service)]


DB = Annotated[Session, Depends(get_db)]


def present(target, user, active=None) -> TargetResponse | TargetPublicResponse:
    model = TargetResponse if is_admin_user(user) else TargetPublicResponse
    response = model.model_validate(target)
    if active is not None:
        response.availability = Availability(**availability(target, active.get(target.id, [])))
    return response


def _active(db: Session):
    repository = ReservationRepository(db)
    from datetime import UTC, datetime

    repository.expire_due(datetime.now(UTC))
    return repository.active_by_target()


@router.get("", response_model=list[TargetResponse | TargetPublicResponse])
def list_targets(
    service: Service,
    db: DB,
    tag: str | None = Query(default=None, max_length=64),
    lab: str | None = Query(default=None, max_length=100),
    user=Depends(get_current_user),
):
    """All targets with live availability (who holds each board and until when)."""
    active = _active(db)
    targets = service.repository.list(tag=tag.strip().lower() if tag else None, lab=lab)
    return [present(target, user, active) for target in targets]


@router.get("/tags", response_model=list[str])
def list_tags(service: Service, _user=Depends(get_current_user)):
    return sorted({tag for target in service.list_targets() for tag in (target.tags or [])})


@router.get("/{target_id}", response_model=TargetResponse | TargetPublicResponse)
def get_target(target_id: str, service: Service, db: DB, user=Depends(get_current_user)):
    return present(service.get_target(target_id), user, _active(db))


@router.post("", response_model=TargetResponse, status_code=201)
def create_target(
    request: TargetCreate,
    service: Service,
    db: DB,
    admin=Depends(require_role("admin")),
):
    target = service.create_target(**request.model_dump())
    AuditService(AuditRepository(db)).record(action="target.create", user_id=admin.username, target_id=target.id, detail=target.name)
    return target


@router.put("/{target_id}", response_model=TargetResponse)
def update_target(
    target_id: str,
    request: TargetUpdate,
    service: Service,
    db: DB,
    admin=Depends(require_role("admin")),
):
    before = service.get_target(target_id).status
    changes = request.model_dump(exclude_unset=True)
    if changes.get("status") == "available" and "status_reason" not in changes:
        changes["status_reason"] = None
    target = service.update_target(target_id, **changes)
    AuditService(AuditRepository(db)).record(
        action="target.update", user_id=admin.username, target_id=target.id, detail=", ".join(sorted(changes))
    )
    if target.status != before:
        reason = f" ({target.status_reason})" if target.status_reason else ""
        Notifier(db).event(
            "target.status",
            f"[{target.name}] is now {target.status}{reason} — set by {admin.username}",
            data={"target": target.name, "status": target.status, "reason": target.status_reason},
            target_id=target.id,
        )
    return target


@router.delete("/{target_id}", status_code=204)
def delete_target(
    target_id: str,
    service: Service,
    db: DB,
    admin=Depends(require_role("admin")),
):
    name = service.get_target(target_id).name
    service.delete_target(target_id)
    AuditService(AuditRepository(db)).record(action="target.delete", user_id=admin.username, target_id=target_id, detail=name)
