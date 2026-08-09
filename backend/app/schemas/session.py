from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class SessionCreate(BaseModel):
    reservation_id: str = Field(min_length=1)
    user_id: str = Field(min_length=1, max_length=100)
    capability_type: str = Field(min_length=1, max_length=32)


class SessionResponse(BaseModel):
    id: str
    reservation_id: str
    target_id: str
    user_id: str
    capability_type: str
    provider_key: str | None = None
    status: str
    expires_at: datetime
    ended_at: datetime | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
