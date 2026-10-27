from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class CapabilityType(StrEnum):
    SERIAL = "serial"
    NETWORK = "network"
    SSH = "ssh"
    TELNET = "telnet"
    FTP = "ftp"
    JLINK = "jlink"
    POWER = "power"
    RESET = "reset"
    DEPLOY = "deploy"


class TargetCapabilityBase(BaseModel):
    name: str
    capability_type: CapabilityType
    agent_id: str | None = None
    resource_id: str | None = None
    provider_key: str | None = None
    provider_config: dict = Field(default_factory=dict)
    enabled: bool = True


class TargetCapabilityCreate(TargetCapabilityBase):
    pass


class TargetCapabilityUpdate(BaseModel):
    name: str | None = None
    capability_type: CapabilityType | None = None
    agent_id: str | None = None
    resource_id: str | None = None
    provider_key: str | None = None
    provider_config: dict | None = None
    enabled: bool | None = None


_FIELDS = (
    "id", "target_id", "name", "capability_type", "agent_id", "resource_id",
    "provider_key", "provider_config", "enabled", "created_at", "updated_at",
)


def _with_execution_labels(value: Any) -> Any:
    """Add hosting (agent/server) and mode (agent/dd/http/simulated/...) derived fields."""
    from app.providers import registry

    if isinstance(value, dict):
        data = dict(value)
    else:
        data = {name: getattr(value, name, None) for name in _FIELDS}
    agent_backed = bool(data.get("agent_id") and data.get("resource_id"))
    capability_type = str(getattr(data.get("capability_type"), "value", data.get("capability_type") or ""))
    try:
        mode = registry.provider_mode(capability_type, data.get("provider_config") or {}, agent_backed)
    except ValueError:
        mode = "invalid"
    resource = getattr(value, "resource", None) if not isinstance(value, dict) else None
    if mode == "agent" and resource is not None:
        metadata = getattr(resource, "resource_metadata", None) or {}
        if metadata.get("simulated") or str(getattr(resource, "resource_key", "")).startswith("sim://"):
            mode = "simulated"
    data["hosting"] = "agent" if agent_backed else "server"
    data["mode"] = mode
    return data


class TargetCapabilityResponse(TargetCapabilityBase):
    id: str
    target_id: str
    hosting: str = "server"
    mode: str = ""
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)

    @model_validator(mode="before")
    @classmethod
    def _labels(cls, value):
        return _with_execution_labels(value)


class TargetCapabilityPublicResponse(BaseModel):
    """Capability view for non-admin users; hides provider and agent internals."""

    id: str
    target_id: str
    name: str
    capability_type: CapabilityType
    enabled: bool
    hosting: str = "server"
    mode: str = ""
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)

    @model_validator(mode="before")
    @classmethod
    def _labels(cls, value):
        return _with_execution_labels(value)
