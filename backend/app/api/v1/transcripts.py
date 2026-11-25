"""Search console transcripts: find the session where a board printed a given message."""

from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user, get_db, is_admin_user
from app.services import transcript_search

router = APIRouter(prefix="/transcripts", tags=["Sessions"])
DB = Annotated[Session, Depends(get_db)]


@router.get("/search")
def search_transcripts(
    db: DB,
    q: Annotated[str, Query(min_length=2, max_length=200, description="Text to find (case-insensitive)")],
    target_id: str | None = None,
    days: Annotated[int, Query(ge=1, le=365)] = 30,
    include_input: bool = False,
    all_users: Annotated[bool, Query(description="Admins only: search everyone's sessions")] = False,
    user=Depends(get_current_user),
) -> dict[str, Any]:
    """Search your own serial transcripts (admins can add ``all_users=true``)."""
    scope = None if (all_users and is_admin_user(user)) else user.username
    result = transcript_search.search(
        db, q, username=scope, target_id=target_id, days=days, include_input=include_input
    )
    for hit in result["hits"]:
        if isinstance(hit["started_at"], datetime):
            hit["started_at"] = hit["started_at"].isoformat()
    return result
