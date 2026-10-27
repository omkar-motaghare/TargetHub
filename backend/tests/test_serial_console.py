"""WebSocket serial console and session transcripts."""

from __future__ import annotations

import json

import pytest
from starlette.websockets import WebSocketDisconnect

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


class EchoBoard:
    """Fake Agent serial device: echoes writes back on the next read."""

    def __init__(self):
        self.pending = "boot ok\r\n"

    def __call__(self, operation):
        name = operation["operation"]
        if name == "write":
            self.pending += f"ECHO:{operation['params']['text']}"
            return {"success": True, "message": "written", "data": {"bytes_written": 1}}
        if name == "read":
            text, self.pending = self.pending, ""
            return {"success": True, "message": "read", "data": {"data_text": text, "bytes_read": len(text)}}
        return {"success": True, "message": name, "data": {}}


def _serial_lab(client):
    admin = bootstrap(client)
    alice = create_user(client, admin, "alice")
    agent_id, credential = enroll_agent(client, admin)
    ids = heartbeat(client, agent_id, credential, [SERIAL])
    target = agent_target(
        client, admin, "BOARD-WS",
        [{"name": "Console", "capability_type": "serial", "agent_id": agent_id, "resource_id": ids["sim://uart0"]}],
    )
    reservation = reserve(client, alice, target["id"])
    session = open_session(client, alice, reservation["id"], "serial")
    return admin, alice, agent_id, credential, session, reservation


def _receive_until(ws, predicate, limit=50):
    seen = []
    for _ in range(limit):
        message = json.loads(ws.receive_text())
        seen.append(message)
        if predicate(message, seen):
            return seen
    raise AssertionError(f"condition not met; got {seen}")


def test_websocket_console_streams_output_and_forwards_input(tmp_path, monkeypatch):
    with api_client(tmp_path, monkeypatch) as (client, _db):
        _admin, alice, agent_id, credential, session, _res = _serial_lab(client)
        with FakeAgent(client, agent_id, credential, EchoBoard()):
            with client.websocket_connect(f"/api/v1/sessions/{session['id']}/serial/ws") as ws:
                ws.send_text(json.dumps({"type": "auth", "token": alice}))
                assert json.loads(ws.receive_text())["type"] == "ready"
                _receive_until(ws, lambda m, _s: m["type"] == "output" and "boot ok" in m["data"])
                ws.send_text(json.dumps({"type": "input", "data": "help\r"}))
                _receive_until(ws, lambda m, _s: m["type"] == "output" and "ECHO:help" in m["data"])

        transcript = client.get(f"/api/v1/sessions/{session['id']}/serial/log", headers=auth(alice))
        assert transcript.status_code == 200
        assert "boot ok" in transcript.text and "ECHO:help" in transcript.text
        with_input = client.get(
            f"/api/v1/sessions/{session['id']}/serial/log?include_input=true", headers=auth(alice)
        )
        assert ">> help" in with_input.text


def test_websocket_rejects_bad_token(tmp_path, monkeypatch):
    with api_client(tmp_path, monkeypatch) as (client, _db):
        _admin, _alice, _agent_id, _credential, session, _res = _serial_lab(client)
        with client.websocket_connect(f"/api/v1/sessions/{session['id']}/serial/ws") as ws:
            ws.send_text(json.dumps({"type": "auth", "token": "garbage"}))
            assert json.loads(ws.receive_text()) == {"type": "closed", "reason": "Authentication failed"}
            with pytest.raises(WebSocketDisconnect):
                ws.receive_text()


def test_websocket_refuses_non_owner(tmp_path, monkeypatch):
    with api_client(tmp_path, monkeypatch) as (client, _db):
        admin, _alice, _agent_id, _credential, session, _res = _serial_lab(client)
        bob = create_user(client, admin, "bob")
        with client.websocket_connect(f"/api/v1/sessions/{session['id']}/serial/ws") as ws:
            ws.send_text(json.dumps({"type": "auth", "token": bob}))
            message = json.loads(ws.receive_text())
            assert message["type"] == "closed" and "owner" in message["reason"].lower()


def test_websocket_closes_when_reservation_is_released(tmp_path, monkeypatch):
    with api_client(tmp_path, monkeypatch) as (client, _db):
        _admin, alice, agent_id, credential, session, reservation = _serial_lab(client)
        with FakeAgent(client, agent_id, credential, EchoBoard()):
            with client.websocket_connect(f"/api/v1/sessions/{session['id']}/serial/ws") as ws:
                ws.send_text(json.dumps({"type": "auth", "token": alice}))
                assert json.loads(ws.receive_text())["type"] == "ready"
                client.post(f"/api/v1/reservations/{reservation['id']}/release", headers=auth(alice))
                seen = _receive_until(ws, lambda m, _s: m["type"] == "closed")
                assert any(word in seen[-1]["reason"].lower() for word in ("closed", "no longer active"))


def test_transcript_is_private(tmp_path, monkeypatch):
    with api_client(tmp_path, monkeypatch) as (client, _db):
        admin, _alice, _agent_id, _credential, session, _res = _serial_lab(client)
        bob = create_user(client, admin, "bob")
        assert client.get(f"/api/v1/sessions/{session['id']}/serial/log", headers=auth(bob)).status_code == 403
        assert client.get(f"/api/v1/sessions/{session['id']}/serial/log", headers=auth(admin)).status_code == 200
