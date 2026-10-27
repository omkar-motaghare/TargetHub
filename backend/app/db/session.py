from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker

from app.core.config import settings


def make_engine(url: str, **kwargs) -> Engine:
    """Create an engine with sane production settings for SQLite and PostgreSQL."""
    if url.startswith("sqlite"):
        connect_args = kwargs.pop("connect_args", {})
        connect_args.setdefault("check_same_thread", False)
        connect_args.setdefault("timeout", 30)
        engine = create_engine(url, connect_args=connect_args, future=True, **kwargs)

        @event.listens_for(engine, "connect")
        def _sqlite_pragmas(dbapi_connection, _record):  # pragma: no cover - trivial
            cursor = dbapi_connection.cursor()
            # WAL lets readers and the writer proceed concurrently; foreign keys
            # enable ON DELETE CASCADE/SET NULL like PostgreSQL.
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA busy_timeout=30000")
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

        return engine
    kwargs.setdefault("pool_pre_ping", True)
    kwargs.setdefault("pool_size", 10)
    kwargs.setdefault("max_overflow", 20)
    return create_engine(url, future=True, **kwargs)


engine = make_engine(settings.database_url)

SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
