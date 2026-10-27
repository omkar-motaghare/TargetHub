"""Shared helpers for API-level tests (temporary SQLite database + TestClient)."""

from __future__ import annotations

import contextlib
import os
import threading
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta

os.environ.setdefault("SECRET_KEY", "test-secret-key")

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.dependencies import get_db
from app.core.config import settings
from app.db.models.user import User  # noqa: F401 - registers the users table
from app.main import app
from app.models.base import Base

BOOTSTRAP_TOKEN = "test-bootstrap-token"
ADMIN = ("admin", "admin12345")


@contextlib.contextmanager
def api_client(tmp_path, monkeypatch) -> Iterator[tuple[TestClient, sessionmaker]]:
    monkeypatch.setattr(settings, "admin_bootstrap_token", BOOTSTRAP_TOKEN)
    engine = create_engine(
        f"sqlite:///{tmp_path / 'api.sqlite3'}", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    session_local = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    def override_get_db():
        db = session_local()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    previous_factory = getattr(app.state, "session_factory", None)
    app.state.session_factory = session_local
    try:
        with TestClient(app) as client:
            yield client, session_local
    finally:
        app.dependency_overrides.clear()
        app.state.session_factory = previous_factory
        engine.dispose()


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def login(client: TestClient, username: str, password: str) -> str:
    response = client.post("/api/v1/auth/token", data={"username": username, "password": password})
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


def bootstrap(client: TestClient) -> str:
    response = client.post(
        "/api/v1/auth/bootstrap",
        json={"username": ADMIN[0], "password": ADMIN[1], "bootstrap_token": BOOTSTRAP_TOKEN},
    )
    assert response.status_code == 201, response.text
    return login(client, *ADMIN)


def create_user(client, admin_token, username, password="user12345", roles=None) -> str:
    response = client.post(
        "/api/v1/auth/users",
        json={"username": username, "password": password, "roles": roles or ["user"]},
        headers=auth(admin_token),
    )
    assert response.status_code in (200, 201), response.text
    return login(client, username, password)


def enroll_agent(client, admin_token, name="lab-agent") -> tuple[str, str]:
    enrollment = client.post(
        "/api/v1/agents/enrollments", json={"agent_name": name}, headers=auth(admin_token)
    )
    assert enrollment.status_code == 201, enrollment.text
    enrolled = client.post(
        "/api/v1/agents/enroll", json={"token": enrollment.json()["token"], "hostname": "lab-host"}
    )
    assert enrolled.status_code == 200, enrolled.text
    return enrolled.json()["agent"]["id"], enrolled.json()["credential"]


def heartbeat(client, agent_id, credential, resources: list[dict]) -> dict:
    response = client.post(
        f"/api/v1/agents/{agent_id}/heartbeat",
        json={"hostname": "lab-host", "resources": resources},
        headers=auth(credential),
    )
    assert response.status_code == 200, response.text
    return {item["resource_key"]: item["id"] for item in response.json()["resources"]}


def reservation_window(minutes: int = 30) -> tuple[str, str]:
    now = datetime.now(UTC)
    return now.isoformat(), (now + timedelta(minutes=minutes)).isoformat()


def reserve(client, token, target_id, minutes: int = 30) -> dict:
    starts_at, ends_at = reservation_window(minutes)
    response = client.post(
        "/api/v1/reservations",
        json={"target_id": target_id, "starts_at": starts_at, "ends_at": ends_at},
        headers=auth(token),
    )
    assert response.status_code == 201, response.text
    return response.json()


def open_session(client, token, reservation_id, capability_type, capability_id=None) -> dict:
    body = {"reservation_id": reservation_id, "capability_type": capability_type}
    if capability_id:
        body["capability_id"] = capability_id
    response = client.post("/api/v1/sessions", json=body, headers=auth(token))
    assert response.status_code == 201, response.text
    return response.json()


def agent_target(client, admin_token, name, capabilities: list[dict]) -> dict:
    response = client.post(
        "/api/v1/targets", json={"name": name, "capabilities": capabilities}, headers=auth(admin_token)
    )
    assert response.status_code == 201, response.text
    return response.json()


class FakeAgent:
    """Polls the hub like the real Agent and answers with a handler function."""

    def __init__(self, client: TestClient, agent_id: str, credential: str, handler: Callable[[dict], dict]):
        self.client = client
        self.agent_id = agent_id
        self.credential = credential
        self.handler = handler
        self.seen: list[dict] = []
        self.errors: list[str] = []
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def _run(self) -> None:
        while not self._stop.is_set():
            polled = self.client.post(
                f"/api/v1/agents/{self.agent_id}/operations/poll",
                json={"wait_seconds": 1, "lease_seconds": 10},
                headers=auth(self.credential),
            )
            if polled.status_code != 200:
                self.errors.append(f"poll {polled.status_code}: {polled.text}")
                return
            operation = polled.json().get("operation")
            if not operation:
                continue
            self.seen.append(operation)
            result = self.handler(operation)
            done = self.client.post(
                f"/api/v1/agents/{self.agent_id}/operations/{operation['id']}/complete",
                json=result,
                headers=auth(self.credential),
            )
            if done.status_code != 200:
                self.errors.append(f"complete {done.status_code}: {done.text}")

    def __enter__(self) -> FakeAgent:
        self._thread.start()
        return self

    def __exit__(self, *_exc) -> None:
        self._stop.set()
        self._thread.join(timeout=5)
