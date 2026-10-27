from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.target_capability import (
    TargetCapabilityCreate,
    TargetCapabilityPublicResponse,
    TargetCapabilityResponse,
)

TargetStatus = Literal["available", "maintenance", "retired"]


def _clean_tags(tags: list[str] | None) -> list[str] | None:
    if tags is None:
        return None
    cleaned: list[str] = []
    for tag in tags:
        value = tag.strip().lower()
        if not value:
            continue
        if len(value) > 64 or not all(char.isalnum() or char in "-_.:/" for char in value):
            raise ValueError(f"invalid tag '{tag}' (letters, digits, - _ . : / ; max 64)")
        if value not in cleaned:
            cleaned.append(value)
    if len(cleaned) > 20:
        raise ValueError("at most 20 tags per target")
    return cleaned


class TargetBase(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    description: str | None = None
    vendor: str | None = Field(default=None, max_length=100)
    board_model: str | None = Field(default=None, max_length=100)
    serial_number: str | None = Field(default=None, max_length=100)
    lab_name: str | None = Field(default=None, max_length=100)
    location: str | None = Field(default=None, max_length=100)
    status: TargetStatus = "available"
    status_reason: str | None = Field(default=None, max_length=500)
    tags: list[str] = Field(default_factory=list)
    enabled: bool = True

    @field_validator("tags", mode="before")
    @classmethod
    def _tags(cls, value):
        return _clean_tags(value) if value is not None else []


class Availability(BaseModel):
    state: str
    reason: str | None = None
    reserved_by: str | None = None
    reserved_until: datetime | None = None
    next_reservation_at: datetime | None = None
    next_reserved_by: str | None = None


class TargetCreate(TargetBase):
    capabilities: list[TargetCapabilityCreate] = Field(default_factory=list)


class TargetUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = None
    vendor: str | None = Field(default=None, max_length=100)
    board_model: str | None = Field(default=None, max_length=100)
    serial_number: str | None = Field(default=None, max_length=100)
    lab_name: str | None = Field(default=None, max_length=100)
    location: str | None = Field(default=None, max_length=100)
    status: TargetStatus | None = None
    status_reason: str | None = Field(default=None, max_length=500)
    tags: list[str] | None = None
    enabled: bool | None = None

    @field_validator("tags", mode="before")
    @classmethod
    def _tags(cls, value):
        return _clean_tags(value)


class TargetResponse(TargetBase):
    id: str
    capabilities: list[TargetCapabilityResponse] = Field(default_factory=list)
    availability: Availability | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class TargetPublicResponse(TargetBase):
    id: str
    capabilities: list[TargetCapabilityPublicResponse] = Field(default_factory=list)
    availability: Availability | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
