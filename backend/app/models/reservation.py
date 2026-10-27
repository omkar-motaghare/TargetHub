from datetime import datetime

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.models.base import Base
from app.models.types import UTCDateTime


class Reservation(Base):
    """Time-bounded ownership of a logical Target."""

    __tablename__ = "reservations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    target_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("targets.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # User identity is intentionally represented as an opaque identifier until
    # the authentication/user domain is implemented. It must come from an
    # authenticated principal in the production access path.
    user_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    starts_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    ends_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active", index=True)
    released_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    note: Mapped[str | None] = mapped_column(String(500))
    # Set once the "ending soon" warning was sent (dedupes across API workers).
    warned_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    released_by: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    target = relationship("Target", back_populates="reservations")
