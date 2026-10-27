import os
import subprocess
import sys
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from app.db.models.user import User
from app.models.agent import Agent, AgentResource
from app.models.agent_operation import AgentOperation
from app.models.audit import AuditLog
from app.models.reservation import Reservation
from app.models.session import TargetSession
from app.models.target import Target
from app.models.target_capability import TargetCapability
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session

os.environ.setdefault("SECRET_KEY", "test-secret-key")


REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_DIR = REPO_ROOT / "backend"
ALEMBIC_INI = BACKEND_DIR / "alembic.ini"
EXPECTED_HEAD = "20261027_04"


def _alembic_head() -> str:
    cfg = Config(str(ALEMBIC_INI))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    script = ScriptDirectory.from_config(cfg)
    heads = script.get_heads()
    assert len(heads) == 1
    return heads[0]


def _run_alembic(db_url: str, *args: str) -> str:
    env = os.environ.copy()
    env["SECRET_KEY"] = "test-secret-key"
    env["DATABASE_URL"] = db_url

    result = subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=BACKEND_DIR,
        env=env,
        text=True,
        capture_output=True,
    )
    if result.returncode != 0:
        raise AssertionError(
            f"alembic {' '.join(args)} failed\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
    return result.stdout + result.stderr


def test_alembic_graph_has_single_head():
    assert _alembic_head() == EXPECTED_HEAD


def test_migrations_apply_to_empty_database_and_reach_head(tmp_path: Path):
    db_path = tmp_path / "empty.sqlite3"
    db_url = f"sqlite:///{db_path}"

    _run_alembic(db_url, "upgrade", "head")

    engine = create_engine(db_url)
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())

    expected = {
        "targets",
        "target_capabilities",
        "reservations",
        "target_sessions",
        "agents",
        "agent_resources",
        "agent_enrollments",
        "agent_operations",
        "users",
        "audit_logs",
        "alembic_version",
    }
    assert expected.issubset(tables)

    with engine.connect() as conn:
        version = conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
    assert version == _alembic_head()


def test_representative_records_can_be_created_after_migrations(tmp_path: Path):
    db_path = tmp_path / "records.sqlite3"
    db_url = f"sqlite:///{db_path}"
    _run_alembic(db_url, "upgrade", "head")

    engine = create_engine(db_url)
    now = datetime.now(UTC)

    with Session(engine) as db:
        user = User(username="dev-user", password_hash="hash", roles="admin", created_at=now)
        target = Target(name="BOARD-01", status="available", enabled=True)
        agent = Agent(name="lab-agent-01", hostname="lab-host", status="online", enabled=True)
        db.add_all([user, target, agent])
        db.flush()

        resource = AgentResource(
            agent_id=agent.id,
            resource_key="/dev/ttyUSB0",
            resource_type="serial",
            display_name="ttyUSB0",
            resource_metadata={"path": "/dev/ttyUSB0"},
            available=True,
        )
        db.add(resource)
        db.flush()

        capability = TargetCapability(
            target_id=target.id,
            agent_id=agent.id,
            resource_id=resource.id,
            name="Serial Console",
            capability_type="serial",
            provider_key="serial-demo",
            provider_config={"baudrate": 115200},
            enabled=True,
        )
        reservation = Reservation(
            id=str(uuid.uuid4()),
            target_id=target.id,
            user_id=user.username,
            starts_at=now,
            ends_at=now + timedelta(minutes=30),
            status="active",
        )
        session = TargetSession(
            id=str(uuid.uuid4()),
            reservation_id=reservation.id,
            target_id=target.id,
            user_id=user.username,
            capability_type="serial",
            provider_key="serial-demo",
            capability_id=capability.id,
            agent_id=agent.id,
            resource_id=resource.id,
            status="active",
            expires_at=now + timedelta(minutes=30),
        )
        operation = AgentOperation(
            agent_id=agent.id,
            session_id=session.id,
            resource_id=resource.id,
            resource_key=resource.resource_key,
            resource_type=resource.resource_type,
            resource_metadata=resource.resource_metadata,
            operation="read",
            params={"size": 32},
            status="completed",
            requested_by=user.username,
            detail="ok",
            result_data={"bytes_read": 0, "data_text": "", "data_hex": ""},
            completed_at=now,
        )
        audit = AuditLog(
            user_id=user.username,
            action="provider.execute",
            target_id=target.id,
            session_id=session.id,
            provider_key="serial-demo",
            capability_type="serial",
            operation="read",
            success=True,
            detail="ok",
        )

        db.add_all([capability, reservation, session, operation, audit])
        db.commit()

    with Session(engine) as db:
        assert db.query(User).count() == 1
        assert db.query(Target).count() == 1
        assert db.query(TargetCapability).count() == 1
        assert db.query(Agent).count() == 1
        assert db.query(AgentResource).count() == 1
        assert db.query(Reservation).count() == 1
        assert db.query(TargetSession).count() == 1
        assert db.query(AgentOperation).count() == 1
        assert db.query(AuditLog).count() == 1


def test_upgrade_from_existing_branch_revision_to_head(tmp_path: Path):
    db_path = tmp_path / "upgrade.sqlite3"
    db_url = f"sqlite:///{db_path}"

    _run_alembic(db_url, "upgrade", "c1d2e3f4a5b6")

    engine = create_engine(db_url)
    tables = set(inspect(engine).get_table_names())
    assert "agent_enrollments" in tables
    assert "users" not in tables
    assert "audit_logs" not in tables

    _run_alembic(db_url, "upgrade", "head")

    tables = set(inspect(engine).get_table_names())
    assert "users" in tables
    assert "audit_logs" in tables

    with engine.connect() as conn:
        version = conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
    assert version == _alembic_head()