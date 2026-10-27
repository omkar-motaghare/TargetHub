from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ReservationCreate(BaseModel):
    target_id: str = Field(min_length=1)
    user_id: str | None = Field(default=None, min_length=1, max_length=100)
    starts_at: datetime
    ends_at: datetime
    note: str | None = Field(default=None, max_length=500)

    @field_validator("ends_at")
    @classmethod
    def validate_end_after_start(cls, value: datetime, info):
        starts_at = info.data.get("starts_at")
        if starts_at is not None and value <= starts_at:
            raise ValueError("ends_at must be after starts_at")
        return value


class ReservationResponse(BaseModel):
    id: str
    target_id: str
    user_id: str
    starts_at: datetime
    ends_at: datetime
    status: str
    note: str | None = None
    released_at: datetime | None = None
    released_by: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ReserveAnyRequest(BaseModel):
    tag: str = Field(min_length=1, max_length=64)
    duration_minutes: int = Field(ge=5, le=60 * 24 * 31)
    starts_at: datetime | None = None
    note: str | None = Field(default=None, max_length=500)


class ExtendRequest(BaseModel):
    ends_at: datetime | None = None
    extend_minutes: int | None = Field(default=None, ge=1, le=60 * 24)


class WaitlistJoin(BaseModel):
    target_id: str | None = None
    tag: str | None = Field(default=None, max_length=64)
    duration_minutes: int = Field(default=60, ge=5, le=60 * 24 * 31)
    note: str | None = Field(default=None, max_length=500)


class WaitlistResponse(BaseModel):
    id: str
    user_id: str
    target_id: str | None = None
    tag: str | None = None
    duration_minutes: int
    note: str | None = None
    status: str
    reservation_id: str | None = None
    created_at: datetime
    expires_at: datetime | None = None
    fulfilled_at: datetime | None = None
    position: int = 0

    model_config = ConfigDict(from_attributes=True)


class NotificationResponse(BaseModel):
    id: str
    kind: str
    message: str
    target_id: str | None = None
    reservation_id: str | None = None
    created_at: datetime
    read_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)
