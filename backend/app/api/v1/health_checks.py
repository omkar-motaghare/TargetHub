"""Admin API for scheduled board health checks (boot banner after power)."""

from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.api.dependencies import get_db, require_role
from app.repositories.audit_repository import AuditRepository
from app.services import health_check_service as checks
from app.services.audit_service import AuditService

router = APIRouter(prefix="/targets/{target_id}/health-check", tags=["Health checks"])
DB = Annotated[Session, Depends(get_db)]


class HealthCheckConfigIn(BaseModel):
    enabled: bool = True
    boot_pattern: str = Field(min_length=1, max_length=200, description="Text expected on the serial console")
    interval_minutes: int = Field(default=1440, ge=5, le=60 * 24 * 7)
    boot_timeout_seconds: int = Field(default=60, ge=10, le=600)
    power_operation: Literal["cycle", "reset", "on"] = "cycle"
    failure_threshold: int = Field(default=2, ge=1, le=10, description="Failures in a row before maintenance")
    auto_maintenance: bool = True


class HealthCheckConfigOut(HealthCheckConfigIn):
    model_config = ConfigDict(from_attributes=True)

    target_id: str
    next_run_at: datetime | None
    last_run_at: datetime | None
    last_status: str | None
    last_message: str | None
    consecutive_failures: int
    maintenance_by_check: bool


class HealthCheckResultOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    status: str
    message: str
    duration_seconds: float
    trigger: str
    started_at: datetime


def _audit(db: Session, user, action: str, target_id: str, detail: str | None = None) -> None:
    AuditService(AuditRepository(db)).record(action=action, user_id=user.username, target_id=target_id, detail=detail)


@router.get("", response_model=HealthCheckConfigOut)
def get_health_check(target_id: str, db: DB, _admin=Depends(require_role("admin"))):
    cfg = checks.get_config(db, target_id)
    if cfg is None:
        raise HTTPException(status_code=404, detail="No health check is configured for this target")
    return cfg


@router.put("", response_model=HealthCheckConfigOut)
def put_health_check(target_id: str, body: HealthCheckConfigIn, db: DB, admin=Depends(require_role("admin"))):
    cfg = checks.save_config(db, target_id, body.model_dump())
    _audit(db, admin, "health_check.configure", target_id, f"enabled={cfg.enabled} every {cfg.interval_minutes} min")
    return cfg


@router.delete("", status_code=204)
def delete_health_check(target_id: str, db: DB, admin=Depends(require_role("admin"))):
    checks.delete_config(db, target_id)
    _audit(db, admin, "health_check.delete", target_id)


@router.get("/results", response_model=list[HealthCheckResultOut])
def health_check_results(target_id: str, db: DB, limit: int = 20, _admin=Depends(require_role("admin"))):
    return checks.recent_results(db, target_id, max(1, min(limit, 100)))


@router.post("/run")
async def run_health_check_now(
    target_id: str, request: Request, db: DB, admin=Depends(require_role("admin"))
) -> dict[str, Any]:
    """Run the check immediately (books the board for the duration; skipped if it is in use)."""
    if checks.get_config(db, target_id) is None:
        raise HTTPException(status_code=404, detail="No health check is configured for this target")
    from app.services.scheduler import _session_factory

    result = await checks.run_health_check(_session_factory(request.app), target_id, "manual")
    _audit(db, admin, "health_check.run", target_id, f"{result['status']}: {result['message']}"[:300])
    return result
