#!/usr/bin/env bash
set -e

echo "======================================="
echo " FEATURE-001 : Target Service Layer"
echo "======================================="

mkdir -p backend/app/services

###############################################################################
# Target Service
###############################################################################

cat > backend/app/services/target_service.py <<'PY'
from app.models.target import Target
from app.repositories.target_repository import TargetRepository


class TargetService:
    def __init__(self, repository: TargetRepository):
        self.repository = repository

    def list_targets(self):
        return self.repository.list()

    def get_target(self, target_id: str):
        return self.repository.get(target_id)

    def create_target(self, **kwargs):
        existing = self.repository.get_by_name(kwargs["name"])

        if existing:
            raise ValueError(
                f"Target '{kwargs['name']}' already exists."
            )

        target = Target(**kwargs)

        return self.repository.create(target)

    def update_target(self, target_id: str, **kwargs):
        target = self.repository.get(target_id)

        if target is None:
            return None

        for key, value in kwargs.items():
            setattr(target, key, value)

        return self.repository.update(target)

    def delete_target(self, target_id: str):
        target = self.repository.get(target_id)

        if target is None:
            return False

        self.repository.delete(target)

        return True
PY

###############################################################################
# __init__.py
###############################################################################

cat > backend/app/services/__init__.py <<'PY'
from .target_service import TargetService

__all__ = [
    "TargetService",
]
PY

###############################################################################
# Format
###############################################################################

cd backend

uv run ruff check . --fix
uv run black .
uv run isort .

echo
echo "✓ TargetService created successfully"
