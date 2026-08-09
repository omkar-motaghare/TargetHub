from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class CapabilityType(StrEnum):
    """Capability families recognized by the TargetHub architecture."""

    SERIAL = "serial"
    NETWORK = "network"
    SSH = "ssh"
    TELNET = "telnet"
    FTP = "ftp"
    JLINK = "jlink"
    POWER = "power"
    RESET = "reset"


class TargetCapabilityBase(BaseModel):
    name: str
    capability_type: CapabilityType
    provider_key: str | None = None
    provider_config: dict = Field(default_factory=dict)
    enabled: bool = True


class TargetCapabilityCreate(TargetCapabilityBase):
    pass


class TargetCapabilityUpdate(BaseModel):
    name: str | None = None
    capability_type: CapabilityType | None = None
    provider_key: str | None = None
    provider_config: dict | None = None
    enabled: bool | None = None


class TargetCapabilityResponse(TargetCapabilityBase):
    id: str
    target_id: str
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
