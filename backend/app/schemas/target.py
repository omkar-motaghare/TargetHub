from datetime import datetime

from pydantic import BaseModel, ConfigDict


class TargetBase(BaseModel):
    name: str
    description: str | None = None
    vendor: str | None = None
    board_model: str | None = None
    serial_number: str | None = None
    lab_name: str | None = None
    location: str | None = None
    status: str = "available"
    enabled: bool = True


class TargetCreate(TargetBase):
    pass


class TargetUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    vendor: str | None = None
    board_model: str | None = None
    serial_number: str | None = None
    lab_name: str | None = None
    location: str | None = None
    status: str | None = None
    enabled: bool | None = None


class TargetResponse(TargetBase):
    id: str
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
