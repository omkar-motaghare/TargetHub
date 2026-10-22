from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user, get_db
from app.repositories.target_repository import TargetRepository

router = APIRouter(prefix="/labs", tags=["Labs"])


@router.get("", response_model=list[str])
def list_labs(
    db: Annotated[Session, Depends(get_db)],
    _user=Depends(get_current_user),
):
    targets = TargetRepository(db).list()
    labs = sorted({t.lab_name for t in targets if t.lab_name})
    return labs
