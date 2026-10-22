from datetime import datetime

from pydantic import BaseModel, ConfigDict


class AuditLogResponse(BaseModel):
    id: str
    user_id: str | None = None
    action: str
    target_id: str | None = None
    session_id: str | None = None
    provider_key: str | None = None
    capability_type: str | None = None
    operation: str | None = None
    success: bool
    detail: str | None = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
