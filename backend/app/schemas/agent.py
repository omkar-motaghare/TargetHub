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


class AgentEnrollmentCreate(BaseModel):
    agent_name: str = Field(min_length=1, max_length=100)
    deployment_scenario: str = Field(pattern="^(same_linux|remote_raspberry_pi|raspberry_pi_all_in_one)$")


class AgentEnrollmentResponse(BaseModel):
    id: str
    agent_name: str
    deployment_scenario: str
    expires_at: datetime
    used_at: datetime | None
    agent_id: str | None
    created_at: datetime
    token: str | None = None
    targethub_url: str | None = None
    install_command: str | None = None

    model_config = ConfigDict(from_attributes=True)


class AgentEnrollRequest(BaseModel):
    token: str = Field(min_length=16)
    hostname: str | None = None


class AgentEnrollResponse(BaseModel):
    agent: "AgentResponse"
    credential: str
    heartbeat_url: str


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
    credential_prefix: str | None = None
    credential_created_at: datetime | None = None
    credential_revoked_at: datetime | None = None
    resources: list[AgentResourceResponse]

    model_config = ConfigDict(from_attributes=True)


AgentEnrollResponse.model_rebuild()
