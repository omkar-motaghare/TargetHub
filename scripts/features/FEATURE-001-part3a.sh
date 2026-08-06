#!/usr/bin/env bash
set -e

echo "======================================="
echo " FEATURE-001 : Target Schemas"
echo "======================================="

mkdir -p backend/app/schemas

cat > backend/app/schemas/target.py <<'PY'
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class TargetBase(BaseModel):
    name: str
    description: str | None = None
    platform: str
    serial_number: str | None = None
    status: str = "AVAILABLE"


class TargetCreate(TargetBase):
    pass


class TargetUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    platform: str | None = None
    serial_number: str | None = None
    status: str | None = None


class TargetResponse(TargetBase):
    id: str
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
PY

cat > backend/app/schemas/__init__.py <<'PY'
from .target import (
    TargetCreate,
    TargetResponse,
    TargetUpdate,
)

__all__ = [
    "TargetCreate",
    "TargetResponse",
    "TargetUpdate",
]
PY

cd backend

uv run ruff check . --fix
uv run black .
uv run isort .

echo
echo "✓ Schemas created"
