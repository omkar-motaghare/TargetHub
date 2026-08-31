#!/usr/bin/env bash
set -e

echo "=========================================="
echo " FEATURE-002 : Reservation Engine"
echo "=========================================="

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
BACKEND="$ROOT/backend"

cd "$BACKEND"

echo
echo "Creating directories..."

mkdir -p app/repositories
mkdir -p app/services
mkdir -p app/schemas
mkdir -p app/api/v1
mkdir -p app/models

############################################################
# Reservation Model
############################################################

cat > app/models/reservation.py <<'EOF'
import uuid

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.models.base import Base


class Reservation(Base):
    __tablename__ = "reservations"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )

    target_id: Mapped[str] = mapped_column(
        ForeignKey("targets.id"),
        nullable=False,
    )

    reserved_by: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )

    created_at: Mapped[DateTime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
EOF

############################################################
# models/__init__.py
############################################################

cat > app/models/__init__.py <<'EOF'
from app.models.base import Base
from app.models.target import Target
from app.models.reservation import Reservation

__all__ = [
    "Base",
    "Target",
    "Reservation",
]
EOF

############################################################
# Reservation Schemas
############################################################

cat > app/schemas/reservation.py <<'EOF'
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class ReservationCreate(BaseModel):
    reserved_by: str


class ReservationResponse(BaseModel):
    id: str
    target_id: str
    reserved_by: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
EOF

############################################################
# schemas/__init__.py
############################################################

cat > app/schemas/__init__.py <<'EOF'
from app.schemas.target import *
from app.schemas.reservation import *
EOF

echo
echo "Part 1 complete."
echo
echo "Continue with FEATURE-002 Part 2."

############################################################
# Reservation Repository
############################################################

cat > app/repositories/reservation_repository.py <<'PYEOF'
from sqlalchemy.orm import Session

from app.models.reservation import Reservation


class ReservationRepository:
    def __init__(self, db: Session):
        self.db = db

    def list(self):
        return self.db.query(Reservation).all()

    def get(self, reservation_id: str):
        return (
            self.db.query(Reservation)
            .filter(Reservation.id == reservation_id)
            .first()
        )

    def get_active_by_target(self, target_id: str):
        return (
            self.db.query(Reservation)
            .filter(Reservation.target_id == target_id)
            .first()
        )

    def create(self, reservation: Reservation):
        self.db.add(reservation)
        self.db.commit()
        self.db.refresh(reservation)
        return reservation

    def delete(self, reservation: Reservation):
        self.db.delete(reservation)
        self.db.commit()
PYEOF

############################################################
# Reservation Service
############################################################

cat > app/services/reservation_service.py <<'PYEOF'
from fastapi import HTTPException

from app.models.reservation import Reservation
from app.repositories.reservation_repository import ReservationRepository
from app.repositories.target_repository import TargetRepository


class ReservationService:
    def __init__(
        self,
        reservation_repository: ReservationRepository,
        target_repository: TargetRepository,
    ):
        self.reservation_repository = reservation_repository
        self.target_repository = target_repository

    def reserve_target(
        self,
        target_id: str,
        reserved_by: str,
    ):
        target = self.target_repository.get(target_id)

        if target is None:
            raise HTTPException(
                status_code=404,
                detail="Target not found",
            )

        existing = self.reservation_repository.get_active_by_target(target_id)

        if existing:
            raise HTTPException(
                status_code=409,
                detail="Target already reserved",
            )

        target.status = "reserved"
        self.target_repository.update(target)

        reservation = Reservation(
            target_id=target_id,
            reserved_by=reserved_by,
        )

        return self.reservation_repository.create(reservation)

    def release_target(
        self,
        target_id: str,
    ):
        reservation = self.reservation_repository.get_active_by_target(
            target_id
        )

        if reservation is None:
            raise HTTPException(
                status_code=404,
                detail="Reservation not found",
            )

        target = self.target_repository.get(target_id)

        target.status = "available"
        self.target_repository.update(target)

        self.reservation_repository.delete(reservation)

    def list(self):
        return self.reservation_repository.list()
PYEOF

############################################################
# Reservation API
############################################################

cat > app/api/v1/reservations.py <<'PYEOF'
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.dependencies import get_db
from app.repositories.reservation_repository import ReservationRepository
from app.repositories.target_repository import TargetRepository
from app.schemas.reservation import (
    ReservationCreate,
    ReservationResponse,
)
from app.services.reservation_service import ReservationService

router = APIRouter(
    prefix="/reservations",
    tags=["Reservations"],
)


def get_service(
    db: Annotated[Session, Depends(get_db)],
):
    return ReservationService(
        ReservationRepository(db),
        TargetRepository(db),
    )


@router.get(
    "",
    response_model=list[ReservationResponse],
)
def list_reservations(
    service: Annotated[
        ReservationService,
        Depends(get_service),
    ],
):
    return service.list()


@router.post(
    "/{target_id}",
    response_model=ReservationResponse,
    status_code=201,
)
def reserve_target(
    target_id: str,
    request: ReservationCreate,
    service: Annotated[
        ReservationService,
        Depends(get_service),
    ],
):
    return service.reserve_target(
        target_id,
        request.reserved_by,
    )


@router.delete(
    "/{target_id}",
    status_code=204,
)
def release_target(
    target_id: str,
    service: Annotated[
        ReservationService,
        Depends(get_service),
    ],
):
    service.release_target(target_id)
PYEOF

echo
echo "Part 2 complete."
echo "Continue with FEATURE-002 Part 3."