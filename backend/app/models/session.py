from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.models.base import Base

ON_DELETE_SET_NULL = "SET NULL"


class TargetSession(Base):
    """Authorized access session bound to an active Target reservation."""

    __tablename__ = "target_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    reservation_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("reservations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    target_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("targets.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    capability_type: Mapped[str] = mapped_column(String(32), nullable=False)
    provider_key: Mapped[str | None] = mapped_column(String(255))
    capability_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("target_capabilities.id", ondelete=ON_DELETE_SET_NULL),
        index=True,
    )
    agent_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("agents.id", ondelete=ON_DELETE_SET_NULL),
        index=True,
    )
    resource_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("agent_resources.id", ondelete=ON_DELETE_SET_NULL),
        index=True,
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active", index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    reservation = relationship("Reservation")
    target = relationship("Target")
    capability = relationship("TargetCapability")
    agent = relationship("Agent")
    resource = relationship("AgentResource")
