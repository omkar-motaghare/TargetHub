from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class AgentResourceCreate(BaseModel):
    resource_key: str
    resource_type: str
    display_name: str
    metadata: dict = Field(default_factory=dict)
    available: bool = True


class AgentResourceResponse(BaseModel):
    id: str
    agent_id: str
    resource_key: str
    resource_type: str
    display_name: str
    metadata: dict = Field(default_factory=dict, validation_alias="resource_metadata")
    available: bool
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class AgentCreate(BaseModel):
    name: str
    hostname: str | None = None


class AgentHeartbeat(BaseModel):
    hostname: str | None = None
    resources: list[AgentResourceCreate] = Field(default_factory=list)


class AgentResponse(BaseModel):
    id: str
    name: str
    hostname: str | None
    status: str
    enabled: bool
    last_seen_at: datetime | None
    resources: list[AgentResourceResponse]

    model_config = ConfigDict(from_attributes=True)
