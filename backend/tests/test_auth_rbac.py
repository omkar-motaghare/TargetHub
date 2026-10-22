import os
from datetime import UTC, datetime, timedelta

os.environ.setdefault("SECRET_KEY", "test-secret-key")

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.dependencies import get_db
from app.core.config import settings
from app.db.models.user import User  # noqa: F401 - ensure users table is registered
from app.main import app
from app.models.agent_operation import AgentOperation
from app.models.base import Base
from app.services.auth_service import AuthService

BOOTSTRAP_TOKEN = "test-bootstrap-token"


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "admin_bootstrap_token", BOOTSTRAP_TOKEN)

    db_path = tmp_path / "auth_rbac.sqlite3"
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    testing_session_local = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    def override_get_db():
        db = testing_session_local()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        test_client.session_factory = testing_session_local
        yield test_client
    app.dependency_overrides.clear()
    engine.dispose()


def bootstrap_admin(client, username="admin", password="admin12345", token=BOOTSTRAP_TOKEN):
    return client.post(
        "/api/v1/auth/bootstrap",
        json={"username": username, "password": password, "bootstrap_token": token},
    )


def login(client, username, password="user12345"):
    response = client.post(
        "/api/v1/auth/token",
        data={"username": username, "password": password, "grant_type": ""},
    )
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


def auth_headers(token):
    return {"Authorization": f"Bearer {token}"}


def create_user(client, admin_token, username, password="user12345", roles=None):
    response = client.post(
        "/api/v1/auth/users",
        json={"username": username, "password": password, "roles": roles or ["user"]},
        headers=auth_headers(admin_token),
    )
    assert response.status_code == 200, response.text
    return response.json()


@pytest.fixture
def admin_token(client):
    bootstrap_admin(client)
    return login(client, "admin", "admin12345")


# --- Bootstrap policy -------------------------------------------------------


def test_bootstrap_creates_first_admin(client):
    response = bootstrap_admin(client)
    assert response.status_code == 201
    assert response.json()["roles"] == ["admin"]


def test_bootstrap_disabled_without_token_configured(client, monkeypatch):
    monkeypatch.setattr(settings, "admin_bootstrap_token", None)
    response = bootstrap_admin(client)
    assert response.status_code == 403


def test_bootstrap_rejects_wrong_token(client):
    response = bootstrap_admin(client, token="wrong-token")
    assert response.status_code == 401


def test_bootstrap_is_one_time_only(client):
    assert bootstrap_admin(client).status_code == 201
    second = bootstrap_admin(client, username="admin2")
    assert second.status_code == 409


# --- Token validation --------------------------------------------------------


def test_missing_token_is_401(client):
    assert client.get("/api/v1/targets").status_code == 401


def test_malformed_authorization_scheme_is_401(client):
    response = client.get("/api/v1/targets", headers={"Authorization": "Token abc123"})
    assert response.status_code == 401


def test_invalid_token_is_401(client):
    response = client.get("/api/v1/targets", headers=auth_headers("not-a-real-token"))
    assert response.status_code == 401


def test_expired_token_is_401(client):
    db = client.session_factory()
    try:
        token = AuthService(db).create_access_token("admin", ["admin"], expires_minutes=-1)
    finally:
        db.close()
    response = client.get("/api/v1/targets", headers=auth_headers(token))
    assert response.status_code == 401


# --- Ordinary user vs admin permissions --------------------------------------


def test_ordinary_user_cannot_create_user(client, admin_token):
    create_user(client, admin_token, "alice")
    alice_token = login(client, "alice")
    response = client.post(
        "/api/v1/auth/users",
        json={"username": "bob", "password": "user12345", "roles": ["user"]},
        headers=auth_headers(alice_token),
    )
    assert response.status_code == 403


def test_admin_can_create_user(client, admin_token):
    body = create_user(client, admin_token, "carol")
    assert body["username"] == "carol"


def test_duplicate_username_is_400(client, admin_token):
    create_user(client, admin_token, "dave")
    response = client.post(
        "/api/v1/auth/users",
        json={"username": "dave", "password": "user12345", "roles": ["user"]},
        headers=auth_headers(admin_token),
    )
    assert response.status_code == 400


def test_admin_can_list_users(client, admin_token):
    create_user(client, admin_token, "role_list_user")
    response = client.get("/api/v1/auth/users", headers=auth_headers(admin_token))
    assert response.status_code == 200
    usernames = [row["username"] for row in response.json()]
    assert "admin" in usernames
    assert "role_list_user" in usernames


def test_ordinary_user_cannot_list_users(client, admin_token):
    create_user(client, admin_token, "role_list_denied")
    denied_token = login(client, "role_list_denied")
    response = client.get("/api/v1/auth/users", headers=auth_headers(denied_token))
    assert response.status_code == 403


def test_admin_can_update_user_roles_and_password(client, admin_token):
    created = create_user(client, admin_token, "role_update_user", password="firstpass123", roles=["user"])
    response = client.put(
        f"/api/v1/auth/users/{created['id']}",
        json={"roles": ["admin", "user"], "password": "changedpass456"},
        headers=auth_headers(admin_token),
    )
    assert response.status_code == 200
    assert sorted(response.json()["roles"]) == ["admin", "user"]

    promoted_token = login(client, "role_update_user", "changedpass456")
    audit_access = client.get("/api/v1/audit", headers=auth_headers(promoted_token))
    assert audit_access.status_code == 200


def test_cannot_remove_last_admin_role(client, admin_token):
    response = client.put(
        "/api/v1/auth/users/1",
        json={"roles": ["user"]},
        headers=auth_headers(admin_token),
    )
    assert response.status_code == 400


def test_admin_can_delete_non_admin_user(client, admin_token):
    created = create_user(client, admin_token, "delete_me_user")
    response = client.delete(f"/api/v1/auth/users/{created['id']}", headers=auth_headers(admin_token))
    assert response.status_code == 204

    list_response = client.get("/api/v1/auth/users", headers=auth_headers(admin_token))
    usernames = [row["username"] for row in list_response.json()]
    assert "delete_me_user" not in usernames


def test_cannot_delete_last_admin_user(client, admin_token):
    response = client.delete("/api/v1/auth/users/1", headers=auth_headers(admin_token))
    assert response.status_code == 400


def test_admin_cannot_delete_currently_authenticated_user(client, admin_token):
    create_user(client, admin_token, "second_admin", password="second12345", roles=["admin"])
    response = client.delete("/api/v1/auth/users/1", headers=auth_headers(admin_token))
    assert response.status_code == 400


# --- Target / capability administration --------------------------------------


def test_ordinary_user_cannot_create_target(client, admin_token):
    create_user(client, admin_token, "erin")
    erin_token = login(client, "erin")
    response = client.post(
        "/api/v1/targets", json={"name": "BOARD-X"}, headers=auth_headers(erin_token)
    )
    assert response.status_code == 403


def test_admin_can_create_target_and_ordinary_user_can_list(client, admin_token):
    create_user(client, admin_token, "frank")
    frank_token = login(client, "frank")

    created = client.post(
        "/api/v1/targets", json={"name": "BOARD-Y"}, headers=auth_headers(admin_token)
    )
    assert created.status_code == 201
    target_id = created.json()["id"]

    listed = client.get("/api/v1/targets", headers=auth_headers(frank_token))
    assert listed.status_code == 200
    assert any(t["id"] == target_id for t in listed.json())


def test_ordinary_user_cannot_add_capability(client, admin_token):
    target = client.post(
        "/api/v1/targets", json={"name": "BOARD-Z"}, headers=auth_headers(admin_token)
    ).json()
    create_user(client, admin_token, "gina")
    gina_token = login(client, "gina")

    response = client.post(
        f"/api/v1/targets/{target['id']}/capabilities",
        json={"name": "Serial", "capability_type": "serial"},
        headers=auth_headers(gina_token),
    )
    assert response.status_code == 403


# --- Reservation / session ownership -----------------------------------------


def _reservation_window():
    now = datetime.now(UTC)
    return now.isoformat(), (now + timedelta(minutes=30)).isoformat()


def test_reservation_and_session_ownership(client, admin_token):
    agent_id, credential = _enroll_agent(client, admin_token, "agent-session-owner")
    heartbeat = client.post(
        f"/api/v1/agents/{agent_id}/heartbeat",
        json={
            "hostname": "owner-test-host",
            "resources": [
                {
                    "resource_key": "/dev/ttyUSB0",
                    "resource_type": "serial",
                    "display_name": "ttyUSB0",
                    "metadata": {"path": "/dev/ttyUSB0"},
                    "available": True,
                }
            ],
        },
        headers=auth_headers(credential),
    )
    assert heartbeat.status_code == 200
    resource_id = heartbeat.json()["resources"][0]["id"]

    target = client.post(
        "/api/v1/targets", json={"name": "BOARD-OWN"}, headers=auth_headers(admin_token)
    ).json()
    capability = client.post(
        f"/api/v1/targets/{target['id']}/capabilities",
        json={
            "name": "Serial",
            "capability_type": "serial",
            "provider_key": "serial-demo",
            "agent_id": agent_id,
            "resource_id": resource_id,
        },
        headers=auth_headers(admin_token),
    )
    assert capability.status_code == 201

    create_user(client, admin_token, "user_a")
    create_user(client, admin_token, "user_b")
    token_a = login(client, "user_a")
    token_b = login(client, "user_b")

    starts_at, ends_at = _reservation_window()
    reservation = client.post(
        "/api/v1/reservations",
        json={"target_id": target["id"], "user_id": "user_a", "starts_at": starts_at, "ends_at": ends_at},
        headers=auth_headers(token_a),
    )
    assert reservation.status_code == 201
    reservation_body = reservation.json()

    forbidden = client.get(
        f"/api/v1/reservations/{reservation_body['id']}", headers=auth_headers(token_b)
    )
    assert forbidden.status_code == 403

    # Ownership violations on an authorized route are a state conflict (409),
    # distinct from missing/insufficient authorization (401/403).
    conflict = client.post(
        f"/api/v1/reservations/{reservation_body['id']}/release", headers=auth_headers(token_b)
    )
    assert conflict.status_code == 409

    session = client.post(
        "/api/v1/sessions",
        json={"reservation_id": reservation_body["id"], "user_id": "user_a", "capability_type": "serial"},
        headers=auth_headers(token_a),
    )
    assert session.status_code == 201
    session_body = session.json()

    forbidden_session = client.get(
        f"/api/v1/sessions/{session_body['id']}", headers=auth_headers(token_b)
    )
    assert forbidden_session.status_code == 403

    owner_ok = client.get(
        f"/api/v1/sessions/{session_body['id']}", headers=auth_headers(token_a)
    )
    assert owner_ok.status_code == 200


def test_ordinary_user_cannot_impersonate_via_user_id(client, admin_token):
    target = client.post(
        "/api/v1/targets", json={"name": "BOARD-IMP"}, headers=auth_headers(admin_token)
    ).json()
    create_user(client, admin_token, "user_c")
    create_user(client, admin_token, "user_d")
    token_c = login(client, "user_c")

    starts_at, ends_at = _reservation_window()
    response = client.post(
        "/api/v1/reservations",
        json={"target_id": target["id"], "user_id": "user_d", "starts_at": starts_at, "ends_at": ends_at},
        headers=auth_headers(token_c),
    )
    assert response.status_code == 403


def test_admin_can_create_reservation_for_another_user(client, admin_token):
    target = client.post(
        "/api/v1/targets", json={"name": "BOARD-ADMIN-IMP"}, headers=auth_headers(admin_token)
    ).json()
    create_user(client, admin_token, "user_e")

    starts_at, ends_at = _reservation_window()
    response = client.post(
        "/api/v1/reservations",
        json={"target_id": target["id"], "user_id": "user_e", "starts_at": starts_at, "ends_at": ends_at},
        headers=auth_headers(admin_token),
    )
    assert response.status_code == 201
    assert response.json()["user_id"] == "user_e"


# --- Agent administration -----------------------------------------------------


def _enroll_agent(client, admin_token, name):
    enrollment = client.post(
        "/api/v1/agents/enrollments",
        json={"agent_name": name},
        headers=auth_headers(admin_token),
    ).json()
    enrolled = client.post(
        "/api/v1/agents/enroll",
        json={"token": enrollment["token"], "hostname": "test-host"},
    ).json()
    return enrolled["agent"]["id"], enrolled["credential"]


def test_ordinary_user_cannot_list_or_read_agents(client, admin_token):
    agent_id, _ = _enroll_agent(client, admin_token, "agent-rbac-read")
    create_user(client, admin_token, "harry")
    harry_token = login(client, "harry")

    assert client.get("/api/v1/agents", headers=auth_headers(harry_token)).status_code == 403
    assert (
        client.get(f"/api/v1/agents/{agent_id}", headers=auth_headers(harry_token)).status_code
        == 403
    )


def test_admin_can_list_agents(client, admin_token):
    _enroll_agent(client, admin_token, "agent-rbac-list")
    response = client.get("/api/v1/agents", headers=auth_headers(admin_token))
    assert response.status_code == 200


def test_agent_heartbeat_requires_agent_credential_not_user_token(client, admin_token):
    agent_id, credential = _enroll_agent(client, admin_token, "agent-rbac-heartbeat")

    no_cred = client.post(
        f"/api/v1/agents/{agent_id}/heartbeat", json={"hostname": "h", "resources": []}
    )
    assert no_cred.status_code == 401

    with_user_token = client.post(
        f"/api/v1/agents/{agent_id}/heartbeat",
        json={"hostname": "h", "resources": []},
        headers=auth_headers(admin_token),
    )
    assert with_user_token.status_code == 401

    with_credential = client.post(
        f"/api/v1/agents/{agent_id}/heartbeat",
        json={"hostname": "h", "resources": []},
        headers=auth_headers(credential),
    )
    assert with_credential.status_code == 200


def test_disabled_agent_credential_cannot_heartbeat(client, admin_token):
    agent_id, credential = _enroll_agent(client, admin_token, "agent-rbac-disable")

    disable_response = client.post(
        f"/api/v1/agents/{agent_id}/disable", headers=auth_headers(admin_token)
    )
    assert disable_response.status_code == 200

    heartbeat = client.post(
        f"/api/v1/agents/{agent_id}/heartbeat",
        json={"hostname": "h", "resources": []},
        headers=auth_headers(credential),
    )
    assert heartbeat.status_code == 401


def test_revoked_agent_credential_cannot_heartbeat(client, admin_token):
    agent_id, credential = _enroll_agent(client, admin_token, "agent-rbac-revoke")

    revoke_response = client.post(
        f"/api/v1/agents/{agent_id}/revoke-credential", headers=auth_headers(admin_token)
    )
    assert revoke_response.status_code == 200

    heartbeat = client.post(
        f"/api/v1/agents/{agent_id}/heartbeat",
        json={"hostname": "h", "resources": []},
        headers=auth_headers(credential),
    )
    assert heartbeat.status_code == 401


def test_agent_heartbeat_rejects_malformed_resource_payload(client, admin_token):
    agent_id, credential = _enroll_agent(client, admin_token, "agent-rbac-malformed")

    heartbeat = client.post(
        f"/api/v1/agents/{agent_id}/heartbeat",
        json={
            "hostname": "h",
            "resources": [
                {
                    "resource_key": "   ",
                    "resource_type": "serial",
                    "display_name": "ttyUSB0",
                    "metadata": {},
                    "available": True,
                }
            ],
        },
        headers=auth_headers(credential),
    )
    assert heartbeat.status_code == 422


def test_agent_operation_poll_requires_agent_credential_not_user_token(client, admin_token):
    agent_id, credential = _enroll_agent(client, admin_token, "agent-rbac-op-poll")

    no_cred = client.post(
        f"/api/v1/agents/{agent_id}/operations/poll",
        json={"wait_seconds": 0, "lease_seconds": 10},
    )
    assert no_cred.status_code == 401

    with_user_token = client.post(
        f"/api/v1/agents/{agent_id}/operations/poll",
        json={"wait_seconds": 0, "lease_seconds": 10},
        headers=auth_headers(admin_token),
    )
    assert with_user_token.status_code == 401

    with_credential = client.post(
        f"/api/v1/agents/{agent_id}/operations/poll",
        json={"wait_seconds": 0, "lease_seconds": 10},
        headers=auth_headers(credential),
    )
    assert with_credential.status_code == 200
    assert with_credential.json()["operation"] is None


def test_agent_operation_complete_requires_matching_agent_credential(client, admin_token):
    agent_id, credential = _enroll_agent(client, admin_token, "agent-rbac-op-complete")
    other_agent_id, other_credential = _enroll_agent(client, admin_token, "agent-rbac-op-other")

    db = client.session_factory()
    try:
        pending = AgentOperation(
            agent_id=agent_id,
            session_id="session-test",
            resource_id="resource-test",
            resource_key="sim://uart0",
            resource_type="serial",
            resource_metadata={"simulated": True},
            operation="open",
            params={},
            status="in_progress",
        )
        db.add(pending)
        db.commit()
        db.refresh(pending)
        operation_id = pending.id
    finally:
        db.close()

    no_cred = client.post(
        f"/api/v1/agents/{agent_id}/operations/{operation_id}/complete",
        json={"success": True, "message": "ok", "data": {}},
    )
    assert no_cred.status_code == 401

    wrong_agent = client.post(
        f"/api/v1/agents/{agent_id}/operations/{operation_id}/complete",
        json={"success": True, "message": "ok", "data": {}},
        headers=auth_headers(other_credential),
    )
    assert wrong_agent.status_code == 403

    right_agent = client.post(
        f"/api/v1/agents/{agent_id}/operations/{operation_id}/complete",
        json={"success": True, "message": "ok", "data": {}},
        headers=auth_headers(credential),
    )
    assert right_agent.status_code == 200
    assert right_agent.json()["status"] == "completed"


def test_ordinary_user_cannot_manage_agents(client, admin_token):
    agent_id, _ = _enroll_agent(client, admin_token, "agent-rbac-manage")
    create_user(client, admin_token, "ivy")
    ivy_token = login(client, "ivy")

    response = client.post(
        f"/api/v1/agents/{agent_id}/disable", headers=auth_headers(ivy_token)
    )
    assert response.status_code == 403


# --- Audit access --------------------------------------------------------------


def test_audit_requires_admin(client, admin_token):
    create_user(client, admin_token, "jack")
    jack_token = login(client, "jack")

    assert client.get("/api/v1/audit", headers=auth_headers(jack_token)).status_code == 403
    assert client.get("/api/v1/audit", headers=auth_headers(admin_token)).status_code == 200
