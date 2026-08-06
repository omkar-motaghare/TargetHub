#!/usr/bin/env bash
set -e

echo "======================================="
echo " FEATURE-001 : Target Repository Layer "
echo "======================================="

mkdir -p backend/app/repositories

###############################################################################
# Repository
###############################################################################

cat > backend/app/repositories/target_repository.py <<'PY'
from sqlalchemy.orm import Session

from app.models.target import Target


class TargetRepository:
    def __init__(self, db: Session):
        self.db = db

    def list(self):
        return self.db.query(Target).all()

    def get(self, target_id: str):
        return (
            self.db.query(Target)
            .filter(Target.id == target_id)
            .first()
        )

    def get_by_name(self, name: str):
        return (
            self.db.query(Target)
            .filter(Target.name == name)
            .first()
        )

    def create(self, target: Target):
        self.db.add(target)
        self.db.commit()
        self.db.refresh(target)
        return target

    def update(self, target: Target):
        self.db.commit()
        self.db.refresh(target)
        return target

    def delete(self, target: Target):
        self.db.delete(target)
        self.db.commit()
PY

###############################################################################
# __init__
###############################################################################

cat > backend/app/repositories/__init__.py <<'PY'
from .target_repository import TargetRepository

__all__ = [
    "TargetRepository",
]
PY

###############################################################################
# Verify
###############################################################################

cd backend

echo
echo "Running formatter..."

uv run ruff check . --fix

uv run black .

uv run isort .

echo
echo "Repository created successfully."

