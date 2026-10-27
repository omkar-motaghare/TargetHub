from __future__ import annotations

from datetime import datetime

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.models.serial_log import SerialLogChunk

# Per-session transcript cap; further output is not stored (the console keeps working).
MAX_TRANSCRIPT_BYTES = 8 * 1024 * 1024


class SerialLogRepository:
    def __init__(self, db: Session):
        self.db = db

    def stored_bytes(self, session_id: str) -> int:
        total = self.db.scalar(
            select(func.coalesce(func.sum(SerialLogChunk.size), 0)).where(
                SerialLogChunk.session_id == session_id
            )
        )
        return int(total or 0)

    def append(self, session_id: str, direction: str, text: str) -> bool:
        if not text:
            return False
        size = len(text.encode("utf-8"))
        if self.stored_bytes(session_id) + size > MAX_TRANSCRIPT_BYTES:
            return False
        self.db.add(SerialLogChunk(session_id=session_id, direction=direction, size=size, data=text))
        self.db.commit()
        return True

    def chunks(self, session_id: str, include_input: bool = False) -> list[SerialLogChunk]:
        statement = (
            select(SerialLogChunk)
            .where(SerialLogChunk.session_id == session_id)
            .order_by(SerialLogChunk.created_at.asc(), SerialLogChunk.id.asc())
        )
        if not include_input:
            statement = statement.where(SerialLogChunk.direction == "out")
        return list(self.db.scalars(statement).all())

    def purge_before(self, cutoff: datetime) -> int:
        result = self.db.execute(delete(SerialLogChunk).where(SerialLogChunk.created_at < cutoff))
        self.db.commit()
        return result.rowcount or 0
