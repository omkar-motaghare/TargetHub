"""Refresh-token rotation, revocation, API tokens, roles, disabled users, hashing."""

from __future__ import annotations

import hashlib
import secrets

from app.db.models.user import User
from app.services.auth_service import AuthService
from tests.helpers import api_client, auth, bootstrap, create_user


def _login(client, username, password):
    response = client.post("/api/v1/auth/token", data={"username": username, "password": password})
    assert response.status_code == 200, response.text
    return response.json()


def test_login_returns_refresh_token_that_rotates(tmp_path, monkeypatch):
    with api_client(tmp_path, monkeypatch) as (client, _db):
        bootstrap(client)
        pair = _login(client, "admin", "admin12345")
        assert pair["refresh_token"].startswith("thr_") and pair["expires_in"] == 900

        rotated = client.post("/api/v1/auth/refresh", json={"refresh_token": pair["refresh_token"]})
        assert rotated.status_code == 200
        new_pair = rotated.json()
        assert new_pair["refresh_token"] != pair["refresh_token"]
        assert client.get("/api/v1/auth/me", headers=auth(new_pair["access_token"])).status_code == 200


def test_reusing_a_rotated_refresh_token_revokes_the_whole_family(tmp_path, monkeypatch):
    with api_client(tmp_path, monkeypatch) as (client, _db):
        bootstrap(client)
        first = _login(client, "admin", "admin12345")["refresh_token"]
        second = client.post("/api/v1/auth/refresh", json={"refresh_token": first}).json()["refresh_token"]
        replay = client.post("/api/v1/auth/refresh", json={"refresh_token": first})
        assert replay.status_code == 401
        # The legitimate newer token is now revoked too (theft detection).
        assert client.post("/api/v1/auth/refresh", json={"refresh_token": second}).status_code == 401


def test_logout_revokes_refresh_token(tmp_path, monkeypatch):
    with api_client(tmp_path, monkeypatch) as (client, _db):
        bootstrap(client)
        pair = _login(client, "admin", "admin12345")
        assert client.post("/api/v1/auth/logout", json={"refresh_token": pair["refresh_token"]}).status_code == 204
        assert client.post("/api/v1/auth/refresh", json={"refresh_token": pair["refresh_token"]}).status_code == 401


def test_logout_all_invalidates_existing_access_tokens(tmp_path, monkeypatch):
    with api_client(tmp_path, monkeypatch) as (client, _db):
        admin = bootstrap(client)
        assert client.post("/api/v1/auth/logout-all", headers=auth(admin)).status_code == 204
        response = client.get("/api/v1/auth/me", headers=auth(admin))
        assert response.status_code == 401 and "revoked" in response.json()["detail"].lower()


def test_password_change_signs_out_other_logins(tmp_path, monkeypatch):
    with api_client(tmp_path, monkeypatch) as (client, _db):
        admin = bootstrap(client)
        pair = _login(client, "admin", "admin12345")
        changed = client.post(
            "/api/v1/auth/change-password",
            json={"username": "admin", "current_password": "admin12345", "new_password": "brand-new-pass"},
        )
        assert changed.status_code == 204
        assert client.get("/api/v1/auth/me", headers=auth(admin)).status_code == 401
        assert client.post("/api/v1/auth/refresh", json={"refresh_token": pair["refresh_token"]}).status_code == 401
        _login(client, "admin", "brand-new-pass")


def test_disabled_user_cannot_log_in_or_use_tokens(tmp_path, monkeypatch):
    with api_client(tmp_path, monkeypatch) as (client, _db):
        admin = bootstrap(client)
        alice = create_user(client, admin, "alice")
        users = {u["username"]: u for u in client.get("/api/v1/auth/users", headers=auth(admin)).json()}
        disabled = client.put(f"/api/v1/auth/users/{users['alice']['id']}", json={"is_active": False}, headers=auth(admin))
        assert disabled.status_code == 200 and disabled.json()["is_active"] is False
        assert client.get("/api/v1/auth/me", headers=auth(alice)).status_code == 401
        assert client.post("/api/v1/auth/token", data={"username": "alice", "password": "user12345"}).status_code == 401


def test_last_admin_cannot_be_disabled(tmp_path, monkeypatch):
    with api_client(tmp_path, monkeypatch) as (client, _db):
        admin = bootstrap(client)
        me = client.get("/api/v1/auth/me", headers=auth(admin)).json()
        response = client.put(f"/api/v1/auth/users/{me['id']}", json={"is_active": False}, headers=auth(admin))
        assert response.status_code == 400


def test_api_token_lifecycle(tmp_path, monkeypatch):
    with api_client(tmp_path, monkeypatch) as (client, _db):
        admin = bootstrap(client)
        alice = create_user(client, admin, "alice")
        created = client.post("/api/v1/auth/api-tokens", json={"name": "ci-runner"}, headers=auth(alice))
        assert created.status_code == 201
        token = created.json()["token"]
        assert token.startswith("thp_")
        me = client.get("/api/v1/auth/me", headers=auth(token))
        assert me.status_code == 200 and me.json()["username"] == "alice"

        listed = client.get("/api/v1/auth/api-tokens", headers=auth(alice)).json()
        assert [item["name"] for item in listed] == ["ci-runner"] and "token" not in listed[0]
        assert listed[0]["last_used_at"] is not None

        # Another user cannot revoke it; the owner can.
        bob = create_user(client, admin, "bob")
        assert client.delete(f"/api/v1/auth/api-tokens/{listed[0]['id']}", headers=auth(bob)).status_code == 404
        assert client.delete(f"/api/v1/auth/api-tokens/{listed[0]['id']}", headers=auth(alice)).status_code == 204
        assert client.get("/api/v1/auth/me", headers=auth(token)).status_code == 401


def test_api_tokens_survive_logout_all_but_not_user_disable(tmp_path, monkeypatch):
    with api_client(tmp_path, monkeypatch) as (client, _db):
        admin = bootstrap(client)
        alice = create_user(client, admin, "alice")
        token = client.post("/api/v1/auth/api-tokens", json={"name": "cli"}, headers=auth(alice)).json()["token"]
        client.post("/api/v1/auth/logout-all", headers=auth(alice))
        assert client.get("/api/v1/auth/me", headers=auth(token)).status_code == 200
        user_id = client.get("/api/v1/auth/me", headers=auth(token)).json()["id"]
        client.put(f"/api/v1/auth/users/{user_id}", json={"is_active": False}, headers=auth(admin))
        assert client.get("/api/v1/auth/me", headers=auth(token)).status_code == 401


def test_viewer_can_browse_but_not_reserve(tmp_path, monkeypatch):
    with api_client(tmp_path, monkeypatch) as (client, _db):
        admin = bootstrap(client)
        viewer = create_user(client, admin, "watcher", roles=["viewer"])
        target = client.post("/api/v1/targets", json={"name": "B1"}, headers=auth(admin)).json()
        assert client.get("/api/v1/targets", headers=auth(viewer)).status_code == 200
        from tests.helpers import reservation_window

        starts, ends = reservation_window()
        denied = client.post(
            "/api/v1/reservations",
            json={"target_id": target["id"], "starts_at": starts, "ends_at": ends},
            headers=auth(viewer),
        )
        assert denied.status_code == 403


def test_unknown_roles_and_bad_usernames_are_rejected(tmp_path, monkeypatch):
    with api_client(tmp_path, monkeypatch) as (client, _db):
        admin = bootstrap(client)
        bad_role = client.post(
            "/api/v1/auth/users", json={"username": "eve", "password": "user12345", "roles": ["root"]}, headers=auth(admin)
        )
        assert bad_role.status_code == 400 and "unknown role" in bad_role.json()["detail"]
        bad_name = client.post(
            "/api/v1/auth/users", json={"username": "a b c", "password": "user12345"}, headers=auth(admin)
        )
        assert bad_name.status_code == 400
        create_user(client, admin, "Dana")
        dup = client.post("/api/v1/auth/users", json={"username": "dana", "password": "user12345"}, headers=auth(admin))
        assert dup.status_code == 400


def test_legacy_password_hash_is_upgraded_on_login(tmp_path, monkeypatch):
    with api_client(tmp_path, monkeypatch) as (client, db_factory):
        bootstrap(client)
        salt = secrets.token_bytes(16)
        legacy = f"{salt.hex()}${hashlib.pbkdf2_hmac('sha256', b'legacy-pass-1', salt, 100_000).hex()}"
        with db_factory() as db:
            user = db.query(User).filter_by(username="admin").one()
            user.password_hash = legacy
            db.commit()
        _login(client, "admin", "legacy-pass-1")
        with db_factory() as db:
            upgraded = db.query(User).filter_by(username="admin").one().password_hash
        assert upgraded.startswith("pbkdf2_sha256$") and AuthService(None)._verify_password("legacy-pass-1", upgraded)


def test_login_is_audited(tmp_path, monkeypatch):
    with api_client(tmp_path, monkeypatch) as (client, _db):
        admin = bootstrap(client)
        client.post("/api/v1/auth/token", data={"username": "admin", "password": "wrong-pass"})
        actions = [entry["action"] for entry in client.get("/api/v1/audit", headers=auth(admin)).json()]
        assert "auth.login" in actions and "auth.login_failed" in actions
