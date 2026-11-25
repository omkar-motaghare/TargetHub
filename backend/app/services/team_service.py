"""Teams: groups of users, and boards that only a team's members (or admins) may reserve.

A board with no team is open to everyone, as before. A board with one or more teams can be
reserved (or waited for) only by members of at least one of them; admins are always allowed.
"""

from __future__ import annotations

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.exceptions import ConflictResource, ResourceNotFound
from app.db.models.user import User
from app.models.target import Target
from app.models.team import Team, TeamMember, TeamTarget


def team_names_for_target(db: Session, target_id: str) -> list[str]:
    return sorted(
        db.scalars(
            select(Team.name).join(TeamTarget, TeamTarget.team_id == Team.id).where(TeamTarget.target_id == target_id)
        ).all()
    )


def team_names_by_target(db: Session) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    rows = db.execute(select(TeamTarget.target_id, Team.name).join(Team, Team.id == TeamTarget.team_id)).all()
    for target_id, name in rows:
        result.setdefault(target_id, []).append(name)
    return {key: sorted(value) for key, value in result.items()}


def can_use_target(db: Session, target_id: str, username: str) -> bool:
    team_ids = db.scalars(select(TeamTarget.team_id).where(TeamTarget.target_id == target_id)).all()
    if not team_ids:
        return True
    return (
        db.scalar(
            select(TeamMember.username).where(TeamMember.team_id.in_(team_ids), TeamMember.username == username)
        )
        is not None
    )


def ensure_can_use(db: Session, target: Target, username: str) -> None:
    if not can_use_target(db, target.id, username):
        teams = ", ".join(team_names_for_target(db, target.id))
        raise ConflictResource(
            f"Target '{target.name}' is restricted to the team(s): {teams}. Ask an admin to add you to one."
        )


def teams_of_user(db: Session, username: str) -> list[str]:
    return sorted(
        db.scalars(
            select(Team.name).join(TeamMember, TeamMember.team_id == Team.id).where(TeamMember.username == username)
        ).all()
    )


def describe(db: Session, team: Team) -> dict:
    members = sorted(db.scalars(select(TeamMember.username).where(TeamMember.team_id == team.id)).all())
    target_ids = sorted(db.scalars(select(TeamTarget.target_id).where(TeamTarget.team_id == team.id)).all())
    return {
        "id": team.id,
        "name": team.name,
        "description": team.description,
        "members": members,
        "target_ids": target_ids,
        "created_at": team.created_at,
    }


def list_teams(db: Session) -> list[dict]:
    return [describe(db, team) for team in db.scalars(select(Team).order_by(Team.name)).all()]


def get_team(db: Session, team_id: str) -> Team:
    team = db.get(Team, team_id)
    if team is None:
        raise ResourceNotFound("Team", team_id)
    return team


def _validated(db: Session, members: list[str], target_ids: list[str]) -> tuple[list[str], list[str]]:
    members = sorted({m.strip() for m in members if m.strip()})
    known_users = set(db.scalars(select(User.username).where(User.username.in_(members or [""]))).all())
    missing = [m for m in members if m not in known_users]
    if missing:
        raise ConflictResource(f"Unknown user(s): {', '.join(missing)}")
    target_ids = sorted(set(target_ids))
    known_targets = set(db.scalars(select(Target.id).where(Target.id.in_(target_ids or [""]))).all())
    if known_targets != set(target_ids):
        raise ConflictResource("One or more targets do not exist")
    return members, target_ids


def _name_taken(db: Session, name: str, except_id: str | None = None) -> bool:
    found = db.scalar(select(Team.id).where(Team.name == name))
    return found is not None and found != except_id


def create_team(db: Session, name: str, description: str | None, members: list[str], target_ids: list[str]) -> Team:
    name = name.strip()
    if _name_taken(db, name):
        raise ConflictResource(f"A team named '{name}' already exists")
    members, target_ids = _validated(db, members, target_ids)
    team = Team(name=name, description=description or None)
    db.add(team)
    db.flush()
    db.add_all([TeamMember(team_id=team.id, username=m) for m in members])
    db.add_all([TeamTarget(team_id=team.id, target_id=t) for t in target_ids])
    db.commit()
    db.refresh(team)
    return team


def update_team(db: Session, team_id: str, changes: dict) -> Team:
    team = get_team(db, team_id)
    if "name" in changes and changes["name"] is not None:
        name = changes["name"].strip()
        if _name_taken(db, name, team.id):
            raise ConflictResource(f"A team named '{name}' already exists")
        team.name = name
    if "description" in changes:
        team.description = changes["description"] or None
    if changes.get("members") is not None or changes.get("target_ids") is not None:
        current = describe(db, team)
        members, target_ids = _validated(
            db,
            changes["members"] if changes.get("members") is not None else current["members"],
            changes["target_ids"] if changes.get("target_ids") is not None else current["target_ids"],
        )
        if changes.get("members") is not None:
            db.execute(delete(TeamMember).where(TeamMember.team_id == team.id))
            db.add_all([TeamMember(team_id=team.id, username=m) for m in members])
        if changes.get("target_ids") is not None:
            db.execute(delete(TeamTarget).where(TeamTarget.team_id == team.id))
            db.add_all([TeamTarget(team_id=team.id, target_id=t) for t in target_ids])
    db.commit()
    db.refresh(team)
    return team


def delete_team(db: Session, team_id: str) -> None:
    team = get_team(db, team_id)
    # Explicit deletes: SQLite ignores ON DELETE CASCADE unless foreign keys are enabled.
    db.execute(delete(TeamMember).where(TeamMember.team_id == team.id))
    db.execute(delete(TeamTarget).where(TeamTarget.team_id == team.id))
    db.delete(team)
    db.commit()
