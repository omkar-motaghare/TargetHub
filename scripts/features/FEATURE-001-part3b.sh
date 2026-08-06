#!/usr/bin/env bash
set -e

echo "========================================="
echo " FEATURE-001 : Target REST API"
echo "========================================="

mkdir -p backend/app/api/v1
mkdir -p backend/app/api

###############################################################################
# Dependencies
###############################################################################

cat > backend/app/api/dependencies.py <<'PY'
from collections.abc import Generator

from sqlalchemy.orm import Session

from app.db.session import SessionLocal


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
PY

###############################################################################
# Target API
###############################################################################

cat > backend/app/api/v1/targets.py <<'PY'
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.dependencies import get_db
from app.repositories.target_repository import TargetRepository
from app.schemas.target import (
    TargetCreate,
    TargetResponse,
    TargetUpdate,
)
from app.services.target_service import TargetService

router = APIRouter(prefix="/targets", tags=["Targets"])


def get_service(db: Session = Depends(get_db)) -> TargetService:
    return TargetService(TargetRepository(db))


@router.get("", response_model=list[TargetResponse])
def list_targets(service: TargetService = Depends(get_service)):
    return service.list_targets()


@router.get("/{target_id}", response_model=TargetResponse)
def get_target(
    target_id: str,
    service: TargetService = Depends(get_service),
):
    target = service.get_target(target_id)

    if target is None:
        raise HTTPException(status_code=404, detail="Target not found")

    return target


@router.post("", response_model=TargetResponse, status_code=201)
def create_target(
    request: TargetCreate,
    service: TargetService = Depends(get_service),
):
    return service.create_target(**request.model_dump())


@router.put("/{target_id}", response_model=TargetResponse)
def update_target(
    target_id: str,
    request: TargetUpdate,
    service: TargetService = Depends(get_service),
):
    target = service.update_target(
        target_id,
        **request.model_dump(exclude_unset=True),
    )

    if target is None:
        raise HTTPException(status_code=404, detail="Target not found")

    return target


@router.delete("/{target_id}", status_code=204)
def delete_target(
    target_id: str,
    service: TargetService = Depends(get_service),
):
    deleted = service.delete_target(target_id)

    if not deleted:
        raise HTTPException(status_code=404, detail="Target not found")
PY

###############################################################################
# API Router
###############################################################################

cat > backend/app/api/router.py <<'PY'
from fastapi import APIRouter

from app.api.v1.targets import router as targets_router

api_router = APIRouter(prefix="/api/v1")

api_router.include_router(targets_router)
PY

###############################################################################
# Package init
###############################################################################

cat > backend/app/api/v1/__init__.py <<'PY'
PY

###############################################################################
# Update main.py
###############################################################################

python3 <<'PY'
from pathlib import Path

path = Path("backend/app/main.py")
text = path.read_text()

imports = """
from app.api.router import api_router
"""

if "from app.api.router import api_router" not in text:
    text = text.replace(
        "from app.core.middleware import RequestMiddleware\n",
        "from app.core.middleware import RequestMiddleware\n"
        + imports,
    )

if "app.include_router(api_router)" not in text:
    text = text.replace(
        'app.add_exception_handler(\n    TargetHubException,\n    targethub_exception_handler,\n)\n',
        '''app.add_exception_handler(
    TargetHubException,
    targethub_exception_handler,
)

app.include_router(api_router)
''',
    )

path.write_text(text)
PY

###############################################################################
# Format
###############################################################################

cd backend

uv run ruff check . --fix
uv run black .
uv run isort .

echo
echo "========================================="
echo "API Created Successfully"
echo "========================================="
