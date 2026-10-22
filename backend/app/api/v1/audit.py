from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.dependencies import get_db, require_role
from app.repositories.audit_repository import AuditRepository
from app.schemas.audit import AuditLogResponse
from app.services.audit_service import AuditService

router = APIRouter(prefix="/audit", tags=["Audit"])


def get_service(db: Annotated[Session, Depends(get_db)]) -> AuditService:
    return AuditService(AuditRepository(db))


Service = Annotated[AuditService, Depends(get_service)]


@router.get("", response_model=list[AuditLogResponse])
def list_audit(
    service: Service,
    _admin=Depends(require_role("admin")),
    user_id: str | None = Query(default=None),
    target_id: str | None = Query(default=None),
    session_id: str | None = Query(default=None),
    limit: int = Query(default=200, ge=1, le=1000),
):
    return service.list(
        user_id=user_id, target_id=target_id, session_id=session_id, limit=limit
    )
