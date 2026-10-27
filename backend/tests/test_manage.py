"""Server console administration (python -m app.manage)."""

from __future__ import annotations

import io

from app import manage
from app.db.models.user import User

from tests.helpers import api_client, bootstrap, create_user


def test_manage_commands(tmp_path, monkeypatch, capsys):
    with api_client(tmp_path, monkeypatch) as (client, db_factory):
        admin = bootstrap(client)
        create_user(client, admin, "alice")
        monkeypatch.setattr(manage, "SessionLocal", db_factory)

        assert manage.main(["list-users"]) == 0
        assert "alice" in capsys.readouterr().out

        assert manage.main(["reset-password", "alice"]) == 0
        password = capsys.readouterr().out.split("Temporary password: ")[1].split()[0]
        login = client.post("/api/v1/auth/token", data={"username": "alice", "password": password})
        assert login.status_code == 200

        monkeypatch.setattr("sys.stdin", io.StringIO("chosen-pass-123\n"))
        assert manage.main(["create-admin", "ops", "--password-stdin"]) == 0
        with db_factory() as db:
            assert db.query(User).filter_by(username="ops").one().role_list == ["admin"]
            assert db.query(User).count() == 3  # nobody was deleted

        assert manage.main(["reset-password", "ghost"]) == 1
