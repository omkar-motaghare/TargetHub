"""Search serial console transcripts across sessions (your own; all of them for admins)."""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.serial_log import SerialLogChunk
from app.models.session import TargetSession
from app.models.target import Target

MAX_SESSIONS_SCANNED = 200
MAX_HITS = 100
MAX_HITS_PER_SESSION = 20
MAX_LINE_CHARS = 300
ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b[@-Z\\-_]")


def _clean(text: str) -> str:
    return ANSI.sub("", text).replace("\r\n", "\n").replace("\r", "\n")


def search(
    db: Session,
    query: str,
    *,
    username: str | None,
    target_id: str | None = None,
    days: int = 30,
    include_input: bool = False,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Case-insensitive substring search over console output (and optionally what users typed).

    ``username=None`` searches everyone's sessions (admin). Output is re-assembled per session before
    matching, so text split across stored chunks is still found. Bounded by session and hit limits.
    """
    needle = query.lower()
    now = now or datetime.now(UTC)
    statement = (
        select(TargetSession)
        .where(TargetSession.created_at >= now - timedelta(days=days))
        .order_by(TargetSession.created_at.desc())
    )
    if username is not None:
        statement = statement.where(TargetSession.user_id == username)
    if target_id:
        statement = statement.where(TargetSession.target_id == target_id)
    sessions = list(db.scalars(statement.where(TargetSession.capability_type == "serial").limit(MAX_SESSIONS_SCANNED + 1)).all())
    truncated = len(sessions) > MAX_SESSIONS_SCANNED
    sessions = sessions[:MAX_SESSIONS_SCANNED]
    names = {t.id: t.name for t in db.scalars(select(Target)).all()}

    hits: list[dict[str, Any]] = []
    for session in sessions:
        chunks = select(SerialLogChunk).where(SerialLogChunk.session_id == session.id)
        if not include_input:
            chunks = chunks.where(SerialLogChunk.direction == "out")
        text = _clean("".join(c.data for c in db.scalars(chunks.order_by(SerialLogChunk.created_at, SerialLogChunk.id)).all()))
        if needle not in text.lower():
            continue
        lines = text.split("\n")
        found = 0
        for number, line in enumerate(lines, start=1):
            if needle not in line.lower():
                continue
            hits.append(
                {
                    "session_id": session.id,
                    "target": names.get(session.target_id, session.target_id),
                    "user_id": session.user_id,
                    "started_at": session.created_at,
                    "line": number,
                    "text": line[:MAX_LINE_CHARS],
                    "before": lines[number - 2][:MAX_LINE_CHARS] if number > 1 else None,
                    "after": lines[number][:MAX_LINE_CHARS] if number < len(lines) else None,
                }
            )
            found += 1
            if found >= MAX_HITS_PER_SESSION or len(hits) >= MAX_HITS:
                break
        if len(hits) >= MAX_HITS:
            truncated = True
            break
    return {"query": query, "sessions_scanned": len(sessions), "truncated": truncated, "hits": hits}
