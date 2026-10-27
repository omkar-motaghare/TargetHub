"""Admin system overview and configuration checks."""

from __future__ import annotations

import os
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.dependencies import get_db, require_role
from app.core.config import settings
from app.db.models.user import User
from app.models.agent import Agent, AgentResource
from app.models.lab import WaitlistEntry
from app.models.reservation import Reservation
from app.models.session import TargetSession
from app.models.target import Target
from app.models.target_capability import TargetCapability
from app.providers.registry import (
    AGENT_FAMILIES,
    CAPABILITY_PROVIDERS,
    SimulationDisabled,
    build_provider,
    provider_mode,
    simulation_allowed,
)
from app.repositories.agent_repository import AgentRepository
from app.services.agent_service import AgentService

router = APIRouter(prefix="/system", tags=["System"])

DB = Annotated[Session, Depends(get_db)]
SECRET_ENV_KEYS = ("api_key_env", "bearer_token_env", "basic_username_env", "basic_password_env")


class Issue(BaseModel):
    severity: Literal["error", "warning"]
    message: str
    target_id: str | None = None
    target_name: str | None = None


class PowerCheckRequest(BaseModel):
    capability_type: Literal["power", "reset"] = "power"
    provider_config: dict[str, Any] = Field(default_factory=dict)


def _capability_issues(db: Session) -> list[Issue]:
    issues: list[Issue] = []
    agents = {agent.id: agent for agent in db.scalars(select(Agent)).all()}
    resources = set(db.scalars(select(AgentResource.id)).all())
    rows = db.execute(
        select(TargetCapability, Target.name, Target.status).join(Target, Target.id == TargetCapability.target_id)
    ).all()
    for capability, target_name, target_status in rows:
        if target_status == "retired":
            continue
        label = f"{target_name} · {capability.name}"

        def add(severity: Literal["error", "warning"], text: str) -> None:
            issues.append(Issue(severity=severity, message=f"{label}: {text}", target_id=capability.target_id,
                                target_name=target_name))

        if not capability.enabled:
            # Disabling an Agent disables its capabilities; re-enable them on the target once it is back.
            add("warning", "capability is disabled, so users cannot open sessions on it")
            continue

        family = CAPABILITY_PROVIDERS.get(capability.capability_type)
        agent_backed = bool(capability.agent_id and capability.resource_id)
        if agent_backed and family in AGENT_FAMILIES:
            agent = agents.get(capability.agent_id)
            if agent is None or capability.resource_id not in resources:
                add("error", "its Agent resource no longer exists; pick a new one")
            elif not agent.enabled:
                add("error", f"Agent '{agent.name}' is disabled")
            elif agent.status != "online":
                add("warning", f"Agent '{agent.name}' is offline")
            continue
        if capability.agent_id and not capability.resource_id:
            add("error", "Agent resource is missing; pick one again")
            continue
        config = capability.provider_config or {}
        try:
            mode = provider_mode(capability.capability_type, config, False)
        except ValueError as exc:
            add("error", str(exc))
            continue
        if mode == "simulated" and not simulation_allowed():
            add("error", "runs in simulated mode, which is disabled on this server")
        if mode == "unconfigured":
            add("error", "power capability has no driver configured")
        for key in SECRET_ENV_KEYS:
            name = config.get(key)
            if name and not os.environ.get(str(name)):
                add("error", f"environment variable {name} ({key}) is not set on the server")
    return issues


@router.get("/overview")
def overview(db: DB, _admin=Depends(require_role("admin"))) -> dict[str, Any]:
    AgentService(AgentRepository(db)).mark_stale_offline()
    targets_by_status = dict(db.execute(select(Target.status, func.count()).group_by(Target.status)).all())
    agents = db.scalars(select(Agent)).all()

    def count(model, *conditions) -> int:
        return int(db.scalar(select(func.count()).select_from(model).where(*conditions)) or 0)

    return {
        "version": settings.app_version,
        "environment": settings.environment,
        "database": db.get_bind().dialect.name,
        "public_url": settings.targethub_public_url,
        "simulation_enabled": simulation_allowed(),
        "scheduler_enabled": settings.scheduler_enabled,
        "targets": {"total": sum(targets_by_status.values()), **targets_by_status},
        "reservations_active": count(Reservation, Reservation.status == "active"),
        "sessions_active": count(TargetSession, TargetSession.status == "active"),
        "waitlist_waiting": count(WaitlistEntry, WaitlistEntry.status == "waiting"),
        "users": {"total": count(User), "active": count(User, User.is_active.is_(True))},
        "agents": {
            "total": len(agents),
            "online": sum(1 for agent in agents if agent.enabled and agent.status == "online"),
            "disabled": sum(1 for agent in agents if not agent.enabled),
        },
        "issues": [issue.model_dump() for issue in _capability_issues(db)],
    }


@router.post("/power-check")
def power_check(request: PowerCheckRequest, _admin=Depends(require_role("admin"))) -> dict[str, Any]:
    """Read-only status call against a server-hosted power configuration (no reservation needed)."""
    try:
        provider = build_provider(request.capability_type, "power-check", request.provider_config)
        result = provider.execute("status")
    except SimulationDisabled as exc:
        return {"success": False, "message": str(exc), "data": None}
    except ValueError as exc:
        return {"success": False, "message": f"Invalid configuration: {exc}", "data": None}
    except Exception as exc:  # noqa: BLE001 - report any driver failure to the admin
        return {"success": False, "message": f"Check failed: {exc}", "data": None}
    return {"success": result.success, "message": result.message, "data": result.data}
