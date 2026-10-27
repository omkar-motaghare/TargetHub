"""Hub-side Agent operation engine: async submission, cleanup on session end, claiming."""

from __future__ import annotations

import time

from app.models.agent_operation import AgentOperation
from sqlalchemy import select

from tests.helpers import (
    FakeAgent,
    agent_target,
    api_client,
    auth,
    bootstrap,
    create_user,
    enroll_agent,
    heartbeat,
    open_session,
    reserve,
)

SERIAL = {"resource_key": "sim://uart0", "resource_type": "serial", "display_name": "uart0", "metadata": {"simulated": True}}
POWER = {"resource_key": "power:relay1", "resource_type": "power", "display_name": "relay", "metadata": {}}


def _lab(client):
    admin = bootstrap(client)
    alice = create_user(client, admin, "alice")
    agent_id, credential = enroll_agent(client, admin)
    ids = heartbeat(client, agent_id, credential, [SERIAL, POWER])
    target = agent_target(
        client,
        admin,
        "BOARD-ASYNC",
        [
            {"name": "Console", "capability_type": "serial", "agent_id": agent_id, "resource_id": ids["sim://uart0"]},
            {
                "name": "Relay",
                "capability_type": "power",
                "agent_id": agent_id,
                "resource_id": ids["power:relay1"],
                "provider_config": {"transport": "agent"},
            },
        ],
    )
    reservation = reserve(client, alice, target["id"])
    return admin, alice, agent_id, credential, target, reservation


def _answer(operation: dict) -> dict:
    if operation["operation"] == "read":
        return {"success": True, "message": "ok", "data": {"data_text": "hi", "bytes_read": 2}}
    return {"success": True, "message": f"{operation['operation']} done", "data": {"state": "on"}}


def test_execute_with_wait_false_returns_202_and_status_endpoint_reports_result(tmp_path, monkeypatch):
    with api_client(tmp_path, monkeypatch) as (client, _db):
        _admin, alice, agent_id, credential, _target, reservation = _lab(client)
        power = open_session(client, alice, reservation["id"], "power")

        queued = client.post(
            f"/api/v1/sessions/{power['id']}/execute?wait=false",
            json={"operation": "cycle"},
            headers=auth(alice),
        )
        assert queued.status_code == 202, queued.text
        body = queued.json()
        assert body["status"] == "pending" and body["operation_id"]

        status_url = f"/api/v1/sessions/{power['id']}/operations/{body['operation_id']}"
        assert client.get(status_url, headers=auth(alice)).json()["status"] == "pending"

        with FakeAgent(client, agent_id, credential, _answer) as agent:
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                state = client.get(status_url, headers=auth(alice)).json()
                if state["status"] == "completed":
                    break
                time.sleep(0.1)
        assert state["status"] == "completed", state
        assert state["message"] == "cycle done"
        assert agent.seen[0]["operation"] == "cycle"


def test_operation_status_is_private_to_session_owner(tmp_path, monkeypatch):
    with api_client(tmp_path, monkeypatch) as (client, _db):
        admin, alice, _agent_id, _credential, _target, reservation = _lab(client)
        bob = create_user(client, admin, "bob")
        power = open_session(client, alice, reservation["id"], "power")
        queued = client.post(
            f"/api/v1/sessions/{power['id']}/execute?wait=false", json={"operation": "on"}, headers=auth(alice)
        ).json()
        url = f"/api/v1/sessions/{power['id']}/operations/{queued['operation_id']}"
        assert client.get(url, headers=auth(bob)).status_code == 409
        assert client.get(url, headers=auth(admin)).status_code == 200


def test_closing_serial_session_queues_agent_cleanup_that_agent_still_receives(tmp_path, monkeypatch):
    with api_client(tmp_path, monkeypatch) as (client, db_factory):
        _admin, alice, agent_id, credential, _target, reservation = _lab(client)
        serial = open_session(client, alice, reservation["id"], "serial")
        with FakeAgent(client, agent_id, credential, _answer) as agent:
            assert client.post(f"/api/v1/sessions/{serial['id']}/serial/open", headers=auth(alice)).status_code == 200
            closed = client.post(f"/api/v1/sessions/{serial['id']}/close", headers=auth(alice))
            assert closed.status_code == 200
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline and not any(
                op["operation"] == "close" and op["params"].get("cleanup") for op in agent.seen
            ):
                time.sleep(0.05)
        cleanup = [op for op in agent.seen if op["operation"] == "close"]
        assert cleanup and cleanup[0]["params"] == {"cleanup": True}
        assert cleanup[0]["session_id"] == serial["id"]


def test_releasing_reservation_queues_cleanup_for_its_serial_sessions(tmp_path, monkeypatch):
    with api_client(tmp_path, monkeypatch) as (client, db_factory):
        _admin, alice, _agent_id, _credential, _target, reservation = _lab(client)
        serial = open_session(client, alice, reservation["id"], "serial")
        open_session(client, alice, reservation["id"], "power")
        assert client.post(f"/api/v1/reservations/{reservation['id']}/release", headers=auth(alice)).status_code == 200
        with db_factory() as db:
            ops = list(db.scalars(select(AgentOperation)).all())
        assert [(op.session_id, op.operation, op.params) for op in ops] == [
            (serial["id"], "close", {"cleanup": True})
        ]


def test_regular_operations_for_closed_sessions_are_cancelled_not_dispatched(tmp_path, monkeypatch):
    with api_client(tmp_path, monkeypatch) as (client, db_factory):
        _admin, alice, agent_id, credential, _target, reservation = _lab(client)
        power = open_session(client, alice, reservation["id"], "power")
        queued = client.post(
            f"/api/v1/sessions/{power['id']}/execute?wait=false", json={"operation": "off"}, headers=auth(alice)
        ).json()
        client.post(f"/api/v1/sessions/{power['id']}/close", headers=auth(alice))
        polled = client.post(
            f"/api/v1/agents/{agent_id}/operations/poll",
            json={"wait_seconds": 0, "lease_seconds": 10},
            headers=auth(credential),
        )
        assert polled.json()["operation"] is None
        status = client.get(
            f"/api/v1/sessions/{power['id']}/operations/{queued['operation_id']}", headers=auth(alice)
        ).json()
        assert status["status"] == "cancelled"


def test_poll_wakes_promptly_when_operation_is_queued(tmp_path, monkeypatch):
    """A long-poll must return as soon as work is queued, not at the end of its wait."""
    import threading

    with api_client(tmp_path, monkeypatch) as (client, _db):
        _admin, alice, agent_id, credential, _target, reservation = _lab(client)
        power = open_session(client, alice, reservation["id"], "power")
        result: dict = {}

        def poll():
            started = time.monotonic()
            response = client.post(
                f"/api/v1/agents/{agent_id}/operations/poll",
                json={"wait_seconds": 10, "lease_seconds": 10},
                headers=auth(credential),
            )
            result["elapsed"] = time.monotonic() - started
            result["operation"] = response.json()["operation"]

        thread = threading.Thread(target=poll)
        thread.start()
        time.sleep(0.5)
        client.post(f"/api/v1/sessions/{power['id']}/execute?wait=false", json={"operation": "on"}, headers=auth(alice))
        thread.join(timeout=15)
        assert result["operation"]["operation"] == "on"
        assert result["elapsed"] < 3


def test_serial_read_accepts_wait_ms_and_rejects_out_of_range(tmp_path, monkeypatch):
    with api_client(tmp_path, monkeypatch) as (client, _db):
        _admin, alice, agent_id, credential, _target, reservation = _lab(client)
        serial = open_session(client, alice, reservation["id"], "serial")
        with FakeAgent(client, agent_id, credential, _answer) as agent:
            read = client.get(
                f"/api/v1/sessions/{serial['id']}/serial/read?wait_ms=500", headers=auth(alice)
            )
            assert read.status_code == 200, read.text
        assert any(op["params"].get("wait_ms") == 500 for op in agent.seen if op["operation"] == "read")
        too_long = client.get(f"/api/v1/sessions/{serial['id']}/serial/read?wait_ms=9000", headers=auth(alice))
        assert too_long.status_code == 422
