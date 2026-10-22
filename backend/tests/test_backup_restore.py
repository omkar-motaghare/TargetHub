import sqlite3
import subprocess
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"


def run(script: str, env: dict, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(SCRIPTS / script), *args], env=env, capture_output=True, text=True
    )


@pytest.fixture
def database(tmp_path):
    path = tmp_path / "hub.sqlite3"
    with sqlite3.connect(path) as conn:
        conn.execute("create table targets (name text)")
        conn.execute("insert into targets values ('board-1')")
    env = {"PATH": "/usr/bin:/bin", "DATABASE_URL": f"sqlite:///{path}"}
    return path, env


def names(path: Path) -> list[str]:
    with sqlite3.connect(path) as conn:
        return [row[0] for row in conn.execute("select name from targets order by name")]


def test_sqlite_backup_restore_round_trip(database, tmp_path):
    path, env = database
    out = tmp_path / "backups"
    backup = run("backup.sh", env, str(out))
    assert backup.returncode == 0, backup.stderr
    file = Path(backup.stdout.strip())
    assert file.exists() and oct(file.stat().st_mode & 0o777) == "0o600"

    with sqlite3.connect(path) as conn:
        conn.execute("insert into targets values ('board-2')")
        conn.execute("delete from targets where name = 'board-1'")
    assert names(path) == ["board-2"]

    restore = run("restore.sh", env, "--yes", str(file))
    assert restore.returncode == 0, restore.stderr
    assert names(path) == ["board-1"]
    assert names(Path(f"{path}.pre-restore")) == ["board-2"]


def test_restore_requires_confirmation_and_valid_checksum(database, tmp_path):
    path, env = database
    backup = run("backup.sh", env, str(tmp_path / "b"))
    file = Path(backup.stdout.strip())

    assert run("restore.sh", env, str(file)).returncode == 2

    file.write_bytes(file.read_bytes() + b"corrupt")
    corrupted = run("restore.sh", env, "--yes", str(file))
    assert corrupted.returncode == 1
    assert "checksum mismatch" in corrupted.stderr
    assert names(path) == ["board-1"]


def test_unsupported_database_url_is_rejected(tmp_path):
    env = {"PATH": "/usr/bin:/bin", "DATABASE_URL": "mysql://x/y"}
    assert run("backup.sh", env, str(tmp_path)).returncode == 1
