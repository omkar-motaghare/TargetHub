import uuid
from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, String, Text, false
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.models.base import Base


class AgentOperation(Base):
    __tablename__ = "agent_operations"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    agent_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("agents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    session_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("target_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    resource_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("agent_resources.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    resource_key: Mapped[str] = mapped_column(String(255), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(64), nullable=False)
    resource_metadata: Mapped[dict] = mapped_column("resource_metadata", JSON, default=dict, nullable=False)
    operation: Mapped[str] = mapped_column(String(32), nullable=False)
    params: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending", index=True)
    requested_by: Mapped[str | None] = mapped_column(String(100))
    # Detached operations are not awaited by an API request (async submit or cleanup).
    detached: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false(), nullable=False)
    detail: Mapped[str | None] = mapped_column(Text)
    result_data: Mapped[dict | None] = mapped_column(JSON)
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    dispatched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    agent = relationship("Agent")
    session = relationship("TargetSession")
    resource = relationship("AgentResource")
