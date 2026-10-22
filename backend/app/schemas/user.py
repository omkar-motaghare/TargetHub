from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class UserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=100)
    password: str = Field(min_length=8)
    roles: list[str] = Field(default_factory=list)


class UserUpdate(BaseModel):
    roles: list[str] | None = None
    password: str | None = Field(default=None, min_length=8)


class ChangePasswordRequest(BaseModel):
    username: str = Field(min_length=3, max_length=100)
    current_password: str = Field(min_length=1)
    new_password: str = Field(min_length=8)


class AdminBootstrapRequest(BaseModel):
    username: str = Field(min_length=3, max_length=100)
    password: str = Field(min_length=8)
    bootstrap_token: str = Field(min_length=1)


class UserResponse(BaseModel):
    id: int
    username: str
    roles: list[str]
    created_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class TokenData(BaseModel):
    username: str | None = None
    roles: list[str] = Field(default_factory=list)
