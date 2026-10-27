from __future__ import annotations

import os
import threading
from datetime import UTC, datetime, timedelta

os.environ.setdefault("SECRET_KEY", "test-secret-key")

from app.api.dependencies import get_db
from app.core.config import settings
from app.db.models.user import User  # noqa: F401 - ensure users table is registered
from app.main import app
from app.models.base import Base
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BOOTSTRAP_TOKEN = "test-bootstrap-token"


def bootstrap_admin(client, username="admin", password="admin12345", token=BOOTSTRAP_TOKEN):
    return client.post(
        "/api/v1/auth/bootstrap",
        json={"username": username, "password": password, "bootstrap_token": token},
    )


def login(client, username, password):
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


def _reservation_window():
    now = datetime.now(UTC)
    return now.isoformat(), (now + timedelta(minutes=30)).isoformat()


def _enroll_agent(client, admin_token, name):
    enrollment = client.post(
        "/api/v1/agents/enrollments",
        json={"agent_name": name},
        headers=auth_headers(admin_token),
    ).json()
    enrolled = client.post(
        "/api/v1/agents/enroll",
        json={"token": enrollment["token"], "hostname": "test-linux-host"},
    ).json()
    return enrolled["agent"]["id"], enrolled["credential"]


def _create_serial_session(client, admin_token, user_token, user_id, suffix):
    agent_id, credential = _enroll_agent(client, admin_token, f"agent-serial-{suffix}")
    heartbeat = client.post(
        f"/api/v1/agents/{agent_id}/heartbeat",
        json={
            "hostname": "test-linux-host",
            "resources": [
                {
                    "resource_key": f"sim://uart-{suffix}",
                    "resource_type": "serial",
                    "display_name": f"sim-uart-{suffix}",
                    "metadata": {"simulated": True},
                    "available": True,
                }
            ],
        },
        headers=auth_headers(credential),
    )
    assert heartbeat.status_code == 200, heartbeat.text
    resource_id = heartbeat.json()["resources"][0]["id"]

    target = client.post(
        "/api/v1/targets",
        json={"name": f"BOARD-SERIAL-{suffix}"},
        headers=auth_headers(admin_token),
    ).json()
    capability = client.post(
        f"/api/v1/targets/{target['id']}/capabilities",
        json={
            "name": "Serial",
            "capability_type": "serial",
            "provider_key": f"serial-agent-{suffix}",
            "agent_id": agent_id,
            "resource_id": resource_id,
        },
        headers=auth_headers(admin_token),
    )
    assert capability.status_code == 201, capability.text

    starts_at, ends_at = _reservation_window()
    reservation = client.post(
        "/api/v1/reservations",
        json={"target_id": target["id"], "user_id": user_id, "starts_at": starts_at, "ends_at": ends_at},
        headers=auth_headers(user_token),
    )
    assert reservation.status_code == 201, reservation.text
    reservation_id = reservation.json()["id"]

    session = client.post(
        "/api/v1/sessions",
        json={"reservation_id": reservation_id, "user_id": user_id, "capability_type": "serial"},
        headers=auth_headers(user_token),
    )
    assert session.status_code == 201, session.text
    return session.json()["id"], reservation_id, agent_id, credential


def _start_fake_agent_worker(client: TestClient, agent_id: str, credential: str):
    stop = threading.Event()
    errors: list[str] = []

    def _worker():
        try:
            while not stop.is_set():
                polled = client.post(
                    f"/api/v1/agents/{agent_id}/operations/poll",
                    json={"wait_seconds": 1, "lease_seconds": 10},
                    headers=auth_headers(credential),
                )
                if polled.status_code != 200:
                    errors.append(f"poll failed: {polled.status_code} {polled.text}")
                    break
                payload = polled.json().get("operation")
                if not payload:
                    continue

                operation = payload["operation"]
                if operation == "read":
                    data = {
                        "bytes_read": 6,
                        "data_text": "ready\n",
                        "data_hex": "72656164790a",
                        "mode": "simulated",
                    }
                elif operation == "write":
                    text = payload.get("params", {}).get("text", "")
                    data = {"bytes_written": len(text.encode("utf-8")), "mode": "simulated"}
                else:
                    data = {"mode": "simulated"}

                completed = client.post(
                    f"/api/v1/agents/{agent_id}/operations/{payload['id']}/complete",
                    json={"success": True, "message": "ok", "data": data},
                    headers=auth_headers(credential),
                )
                if completed.status_code != 200:
                    errors.append(
                        f"complete failed: {completed.status_code} {completed.text}"
                    )
                    break
        except Exception as exc:  # pragma: no cover - defensive worker diagnostics
            errors.append(str(exc))

    thread = threading.Thread(target=_worker, daemon=True)
    thread.start()
    return stop, thread, errors


def test_serial_session_operations_flow_through_agent_poll_protocol(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "admin_bootstrap_token", BOOTSTRAP_TOKEN)
    db_path = tmp_path / "serial_flow.sqlite3"
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
    with TestClient(app) as client:
        bootstrap_admin(client)
        admin_token = login(client, "admin", "admin12345")
        create_user(client, admin_token, "serial_user")
        user_token = login(client, "serial_user", "user12345")
        session_id, _reservation_id, agent_id, credential = _create_serial_session(
            client,
            admin_token,
            user_token,
            "serial_user",
            "flow",
        )

        stop, thread, errors = _start_fake_agent_worker(client, agent_id, credential)
        try:
            write_response = client.post(
                f"/api/v1/sessions/{session_id}/serial/write",
                json={"text": "hello"},
                headers=auth_headers(user_token),
            )
            assert write_response.status_code == 200, write_response.text
            assert write_response.json()["operation"] == "write"
            assert write_response.json()["data"]["bytes_written"] == 5

            read_response = client.get(
                f"/api/v1/sessions/{session_id}/serial/read",
                headers=auth_headers(user_token),
            )
            assert read_response.status_code == 200, read_response.text
            assert read_response.json()["operation"] == "read"
            assert read_response.json()["data"]["data_text"] == "ready\n"

            closed = client.post(
                f"/api/v1/sessions/{session_id}/close",
                headers=auth_headers(user_token),
            )
            assert closed.status_code == 200, closed.text

            after_close = client.post(
                f"/api/v1/sessions/{session_id}/serial/open",
                headers=auth_headers(user_token),
            )
            assert after_close.status_code == 409
            assert "closed" in after_close.json()["detail"].lower()
        finally:
            stop.set()
            thread.join(timeout=2)
        assert not errors, errors

    app.dependency_overrides.clear()
    engine.dispose()


def test_serial_operation_rejects_disabled_or_non_owner_paths(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "admin_bootstrap_token", BOOTSTRAP_TOKEN)
    db_path = tmp_path / "serial_errors.sqlite3"
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
    with TestClient(app) as client:
        bootstrap_admin(client)
        admin_token = login(client, "admin", "admin12345")
        create_user(client, admin_token, "owner")
        create_user(client, admin_token, "intruder")
        owner_token = login(client, "owner", "user12345")
        intruder_token = login(client, "intruder", "user12345")
        session_id, _reservation_id, agent_id, credential = _create_serial_session(
            client,
            admin_token,
            owner_token,
            "owner",
            "errors",
        )

        forbidden = client.post(
            f"/api/v1/sessions/{session_id}/serial/open",
            headers=auth_headers(intruder_token),
        )
        assert forbidden.status_code == 409
        assert "owner" in forbidden.json()["detail"].lower()

        disable = client.post(
            f"/api/v1/agents/{agent_id}/disable",
            headers=auth_headers(admin_token),
        )
        assert disable.status_code == 200

        no_longer_allowed = client.post(
            f"/api/v1/sessions/{session_id}/serial/open",
            headers=auth_headers(owner_token),
        )
        assert no_longer_allowed.status_code == 409
        assert any(
            marker in no_longer_allowed.json()["detail"].lower()
            for marker in ("disabled", "unavailable")
        )

        # Credential is now disabled, so polling must fail with 401.
        poll = client.post(
            f"/api/v1/agents/{agent_id}/operations/poll",
            json={"wait_seconds": 0, "lease_seconds": 10},
            headers=auth_headers(credential),
        )
        assert poll.status_code == 401

    app.dependency_overrides.clear()
    engine.dispose()


def test_releasing_reservation_closes_session_and_blocks_serial_access(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "admin_bootstrap_token", BOOTSTRAP_TOKEN)
    db_path = tmp_path / "serial_release.sqlite3"
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
    with TestClient(app) as client:
        bootstrap_admin(client)
        admin_token = login(client, "admin", "admin12345")
        create_user(client, admin_token, "serial_user")
        user_token = login(client, "serial_user", "user12345")
        session_id, reservation_id, agent_id, credential = _create_serial_session(
            client,
            admin_token,
            user_token,
            "serial_user",
            "release",
        )

        stop, thread, errors = _start_fake_agent_worker(client, agent_id, credential)
        try:
            baseline = client.post(
                f"/api/v1/sessions/{session_id}/serial/open",
                headers=auth_headers(user_token),
            )
            assert baseline.status_code == 200, baseline.text

            released = client.post(
                f"/api/v1/reservations/{reservation_id}/release",
                headers=auth_headers(user_token),
            )
            assert released.status_code == 200, released.text

            session_state = client.get(
                f"/api/v1/sessions/{session_id}",
                headers=auth_headers(user_token),
            )
            assert session_state.status_code == 200, session_state.text
            assert session_state.json()["status"] == "closed"

            after_release = client.post(
                f"/api/v1/sessions/{session_id}/serial/open",
                headers=auth_headers(user_token),
            )
            assert after_release.status_code == 409
            assert "closed" in after_release.json()["detail"].lower()
        finally:
            stop.set()
            thread.join(timeout=2)
        assert not errors, errors

    app.dependency_overrides.clear()
    engine.dispose()
