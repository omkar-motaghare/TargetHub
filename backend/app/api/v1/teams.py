"""Teams (admin): groups of users, and the boards restricted to them."""

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user, get_db, require_role
from app.repositories.audit_repository import AuditRepository
from app.services import team_service
from app.services.audit_service import AuditService

router = APIRouter(prefix="/teams", tags=["Teams"])
DB = Annotated[Session, Depends(get_db)]


class TeamCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=500)
    members: list[str] = Field(default_factory=list, max_length=500)
    target_ids: list[str] = Field(default_factory=list, max_length=500)


class TeamUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=500)
    members: list[str] | None = Field(default=None, max_length=500)
    target_ids: list[str] | None = Field(default=None, max_length=500)


class TeamResponse(BaseModel):
    id: str
    name: str
    description: str | None
    members: list[str]
    target_ids: list[str]
    created_at: datetime | None = None


@router.get("", response_model=list[TeamResponse])
def list_teams(db: DB, _admin=Depends(require_role("admin"))):
    return team_service.list_teams(db)


@router.get("/mine", response_model=list[str])
def my_teams(db: DB, user=Depends(get_current_user)):
    """Names of the teams you belong to."""
    return team_service.teams_of_user(db, user.username)


@router.post("", response_model=TeamResponse, status_code=201)
def create_team(request: TeamCreate, db: DB, admin=Depends(require_role("admin"))):
    team = team_service.create_team(db, request.name, request.description, request.members, request.target_ids)
    AuditService(AuditRepository(db)).record(action="team.create", user_id=admin.username, detail=team.name)
    return team_service.describe(db, team)


@router.put("/{team_id}", response_model=TeamResponse)
def update_team(team_id: str, request: TeamUpdate, db: DB, admin=Depends(require_role("admin"))):
    team = team_service.update_team(db, team_id, request.model_dump(exclude_unset=True))
    AuditService(AuditRepository(db)).record(action="team.update", user_id=admin.username, detail=team.name)
    return team_service.describe(db, team)


@router.delete("/{team_id}", status_code=204)
def delete_team(team_id: str, db: DB, admin=Depends(require_role("admin"))):
    name = team_service.get_team(db, team_id).name
    team_service.delete_team(db, team_id)
    AuditService(AuditRepository(db)).record(action="team.delete", user_id=admin.username, detail=name)
