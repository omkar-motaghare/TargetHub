from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict


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
    enabled: bool = True


class TargetCapabilityCreate(TargetCapabilityBase):
    pass


class TargetCapabilityResponse(TargetCapabilityBase):
    id: str
    target_id: str
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
