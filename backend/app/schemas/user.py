from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class UserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=100)
    password: str = Field(min_length=8, max_length=256)
    roles: list[str] = Field(default_factory=list)
    display_name: str | None = Field(default=None, max_length=200)
    email: str | None = Field(default=None, max_length=320)


class UserUpdate(BaseModel):
    roles: list[str] | None = None
    password: str | None = Field(default=None, min_length=8, max_length=256)
    is_active: bool | None = None
    display_name: str | None = Field(default=None, max_length=200)
    email: str | None = Field(default=None, max_length=320)


class ChangePasswordRequest(BaseModel):
    username: str = Field(min_length=3, max_length=100)
    current_password: str = Field(min_length=1)
    new_password: str = Field(min_length=8, max_length=256)


class AdminBootstrapRequest(BaseModel):
    username: str = Field(min_length=3, max_length=100)
    password: str = Field(min_length=8, max_length=256)
    bootstrap_token: str = Field(min_length=1)


class UserResponse(BaseModel):
    id: int
    username: str
    roles: list[str]
    display_name: str | None = None
    email: str | None = None
    is_active: bool = True
    last_login_at: datetime | None = None
    created_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)

    @classmethod
    def of(cls, user) -> "UserResponse":
        return cls(
            id=user.id,
            username=user.username,
            roles=user.role_list,
            display_name=user.display_name,
            email=user.email,
            is_active=bool(user.is_active),
            last_login_at=user.last_login_at,
            created_at=user.created_at,
        )


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
    refresh_token: str | None = None
    expires_in: int | None = None


class RefreshRequest(BaseModel):
    refresh_token: str = Field(min_length=10, max_length=200)


class ApiTokenCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    expires_days: int | None = Field(default=None, ge=1, le=3650)


class ApiTokenResponse(BaseModel):
    id: str
    name: str
    prefix: str
    created_at: datetime
    expires_at: datetime | None = None
    last_used_at: datetime | None = None
    revoked_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class ApiTokenCreated(ApiTokenResponse):
    token: str = Field(description="Shown once; store it securely")


class TokenData(BaseModel):
    username: str | None = None
    roles: list[str] = Field(default_factory=list)
