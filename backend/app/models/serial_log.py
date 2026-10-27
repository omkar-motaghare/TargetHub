import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.models.base import Base


class SerialLogChunk(Base):
    """Console traffic relayed through the hub for a serial session (transcript)."""

    __tablename__ = "serial_log_chunks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    session_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("target_sessions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # "out" = target -> user, "in" = user -> target
    direction: Mapped[str] = mapped_column(String(3), nullable=False, default="out")
    size: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    data: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
