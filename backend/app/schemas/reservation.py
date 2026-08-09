from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ReservationCreate(BaseModel):
    target_id: str = Field(min_length=1)
    user_id: str = Field(min_length=1, max_length=100)
    starts_at: datetime
    ends_at: datetime

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
    released_at: datetime | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
