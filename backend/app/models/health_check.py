import uuid
from datetime import datetime

from sqlalchemy import Boolean, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.models.base import Base
from app.models.types import UTCDateTime


class HealthCheck(Base):
    """Scheduled boot check for one target: power it, then expect a banner on the serial console."""

    __tablename__ = "target_health_checks"

    target_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("targets.id", ondelete="CASCADE"), primary_key=True
    )
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    interval_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=1440)
    boot_pattern: Mapped[str] = mapped_column(String(200), nullable=False)
    boot_timeout_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=60)
    power_operation: Mapped[str] = mapped_column(String(16), nullable=False, default="cycle")
    failure_threshold: Mapped[int] = mapped_column(Integer, nullable=False, default=2)
    auto_maintenance: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    next_run_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True, index=True)
    last_run_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    # passed | failed | skipped
    last_status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    last_message: Mapped[str | None] = mapped_column(String(500), nullable=True)
    consecutive_failures: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # True while the target is in maintenance because of this check, so a later pass can restore it.
    maintenance_by_check: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class HealthCheckResult(Base):
    __tablename__ = "target_health_results"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    target_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("targets.id", ondelete="CASCADE"), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    message: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    duration_seconds: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    trigger: Mapped[str] = mapped_column(String(16), nullable=False, default="schedule")
    started_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), server_default=func.now(), nullable=False, index=True
    )
