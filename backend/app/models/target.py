import uuid

from sqlalchemy import Boolean, DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.models.base import Base


class Target(Base):
    """Logical embedded target managed by TargetHub."""

    __tablename__ = "targets"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )

    name: Mapped[str] = mapped_column(
        String(100),
        unique=True,
        nullable=False,
    )

    description: Mapped[str | None] = mapped_column(Text)
    vendor: Mapped[str | None] = mapped_column(String(100))
    board_model: Mapped[str | None] = mapped_column(String(100))

    serial_number: Mapped[str | None] = mapped_column(
        String(100),
        unique=True,
    )

    lab_name: Mapped[str | None] = mapped_column(String(100))
    location: Mapped[str | None] = mapped_column(String(100))

    # Operational state. Reservation ownership will be modeled separately
    # by the Reservation domain and must not be inferred from this field.
    status: Mapped[str] = mapped_column(
        String(32),
        default="available",
        nullable=False,
    )

    enabled: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
    )

    created_at: Mapped[DateTime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )

    updated_at: Mapped[DateTime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )

    capabilities = relationship(
        "TargetCapability",
        back_populates="target",
        cascade="all, delete-orphan",
        order_by="TargetCapability.name",
    )
