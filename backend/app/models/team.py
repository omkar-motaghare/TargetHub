import uuid

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.models.base import Base
from app.models.types import UTCDateTime


class Team(Base):
    """A group of users. Boards can be limited to one or more teams."""

    __tablename__ = "teams"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(String(500))
    created_at = mapped_column(UTCDateTime(), server_default=func.now())


class TeamMember(Base):
    __tablename__ = "team_members"

    team_id: Mapped[str] = mapped_column(String(36), ForeignKey("teams.id", ondelete="CASCADE"), primary_key=True)
    username: Mapped[str] = mapped_column(String(100), primary_key=True)


class TeamTarget(Base):
    """A board that only the team's members (and admins) may reserve."""

    __tablename__ = "team_targets"

    team_id: Mapped[str] = mapped_column(String(36), ForeignKey("teams.id", ondelete="CASCADE"), primary_key=True)
    target_id: Mapped[str] = mapped_column(String(36), ForeignKey("targets.id", ondelete="CASCADE"), primary_key=True)
