"""TCP tunnels (SSH/Telnet/GDB remote) through the Agent: runtime, hub relay and limits."""

from __future__ import annotations

import base64
import importlib.util
import json
import socket
import sys
import threading
from pathlib import Path

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

RUNTIME_PATH = Path(__file__).resolve().parents[1] / "app" / "web" / "agent" / "targethub_agent.py"


@pytest.fixture(scope="module")
def agent_module():
    spec = importlib.util.spec_from_file_location("targethub_agent_tunnel", RUNTIME_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class EchoServer:
    """A real local TCP server: greets, then echoes everything back upper-cased."""

    def __init__(self, hang_up_after: int | None = None):
        self.sock = socket.socket()
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(5)
        self.port = self.sock.getsockname()[1]
        self.hang_up_after = hang_up_after
        self.connections = 0
        threading.Thread(target=self._serve, daemon=True).start()

    def _serve(self):
        while True:
            try:
                conn, _ = self.sock.accept()
            except OSError:
                return
            self.connections += 1
            threading.Thread(target=self._handle, args=(conn,), daemon=True).start()

    def _handle(self, conn):
        received = 0
        with conn:
            conn.sendall(b"SSH-2.0-fake\r\n")
            while True:
                try:
                    data = conn.recv(4096)
                except OSError:
                    return
                if not data:
                    return
                received += len(data)
                conn.sendall(data.upper())
                if self.hang_up_after is not None and received >= self.hang_up_after:
                    return

    def close(self):
        self.sock.close()


@pytest.fixture
def echo():
    server = EchoServer()
    yield server
    server.close()


def tunnel_config(port: int, **extra) -> dict:
    return {
        "resources": [
            {
                "resource_key": "tunnel:board-ssh",
                "resource_type": "tunnel",
                "display_name": "Board SSH",
                "metadata": {"host": "127.0.0.1", "port": port, **extra},
            }
        ]
    }


def op(operation, session="s1", **params):
    return {
        "session_id": session,
        "resource_id": "r1",
        "resource_key": "tunnel:board-ssh",
        "resource_type": "tunnel",
        "resource_metadata": {},
        "operation": operation,
        "params": params,
    }


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


def read_all(router, session="s1", expect=1, tries=20):
    got = b""
    for _ in range(tries):
        result = router.execute(op("read", session, size=4096, wait_ms=200))
        assert result["success"], result
        got += base64.b64decode(result["data"]["data_b64"])
        if len(got) >= expect:
            break
    return got


# ---------------------------------------------------------------- agent runtime


def test_agent_tunnel_roundtrip_with_binary_data(agent_module, echo):
    router = agent_module.OperationRouter(tunnel_config(echo.port))
    try:
        assert router.execute(op("open"))["success"]
        assert read_all(router, expect=14) == b"SSH-2.0-fake\r\n"
        payload = bytes(range(256))
        assert router.execute(op("write", data_b64=b64(b"hello")))["success"]
        assert read_all(router, expect=5) == b"HELLO"
        assert router.execute(op("write", data_b64=b64(payload)))["success"]
        assert read_all(router, expect=256) == payload.upper()
    finally:
        router.tunnel.close_all()


def test_agent_tunnel_destination_comes_only_from_local_config(agent_module, echo):
    router = agent_module.OperationRouter(tunnel_config(echo.port))
    forged = op("open")
    forged["resource_metadata"] = {"host": "10.9.9.9", "port": 1}
    forged["params"] = {"host": "10.9.9.9", "port": 1}
    try:
        assert router.execute(forged)["success"]
        assert echo.connections == 1
    finally:
        router.tunnel.close_all()


def test_agent_tunnel_rejects_unconfigured_resource_and_bad_writes(agent_module, echo):
    router = agent_module.OperationRouter({"resources": []})
    assert "not configured" in router.execute(op("open"))["message"]

    router = agent_module.OperationRouter(tunnel_config(echo.port))
    try:
        assert not router.execute(op("write", data_b64=b64(b"x")))["success"]  # not open
        assert router.execute(op("open"))["success"]
        assert not router.execute(op("write", data_b64="***"))["success"]
        too_big = b64(bytes(agent_module.MAX_TUNNEL_WRITE_BYTES + 1))
        assert "too large" in router.execute(op("write", data_b64=too_big))["message"]
    finally:
        router.tunnel.close_all()


def test_agent_tunnel_new_session_takes_over(agent_module, echo):
    router = agent_module.OperationRouter(tunnel_config(echo.port))
    try:
        assert router.execute(op("open", "s1"))["success"]
        assert router.execute(op("open", "s2"))["success"]
        assert not router.execute(op("write", "s1", data_b64=b64(b"x")))["success"]
        # A stale cleanup close from the old session leaves the new owner alone.
        assert router.execute(op("close", "s1"))["success"]
        assert router.execute(op("write", "s2", data_b64=b64(b"ok")))["success"]
    finally:
        router.tunnel.close_all()


def test_agent_tunnel_reports_eof_and_can_reopen(agent_module):
    server = EchoServer(hang_up_after=3)
    router = agent_module.OperationRouter(tunnel_config(server.port))
    try:
        assert router.execute(op("open"))["success"]
        router.execute(op("write", data_b64=b64(b"abc")))
        eof = False
        for _ in range(20):
            result = router.execute(op("read", size=4096, wait_ms=200))
            if result["data"]["eof"]:
                eof = True
                break
        assert eof
        assert not router.execute(op("write", data_b64=b64(b"more")))["success"]
        assert router.execute(op("open"))["success"]  # same session reconnects
        assert server.connections == 2
    finally:
        router.tunnel.close_all()
        server.close()


def test_agent_tunnel_connect_failure_is_reported(agent_module):
    probe = socket.socket()
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
    probe.close()
    router = agent_module.OperationRouter(tunnel_config(port))
    result = router.execute(op("open"))
    assert not result["success"] and "Could not connect" in result["message"]


def test_agent_tunnel_starts_and_stops_helper_command(agent_module, tmp_path):
    port_probe = socket.socket()
    port_probe.bind(("127.0.0.1", 0))
    port = port_probe.getsockname()[1]
    port_probe.close()
    server_script = tmp_path / "server.py"
    server_script.write_text(
        "import socket, sys\n"
        "s = socket.socket(); s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)\n"
        f"s.bind(('127.0.0.1', {port})); s.listen(1)\n"
        "c, _ = s.accept(); c.sendall(b'GDB ready'); c.recv(10)\n"
    )
    router = agent_module.OperationRouter(
        tunnel_config(port, command=[sys.executable, str(server_script)], start_timeout=10)
    )
    try:
        assert router.execute(op("open"))["success"]
        assert read_all(router, expect=9) == b"GDB ready"
        process = router.tunnel._channels["r1"].process
        assert process is not None and process.poll() is None
        assert router.execute(op("close"))["success"]
        assert process.poll() is not None  # helper stopped with the tunnel
    finally:
        router.tunnel.close_all()


def test_agent_does_not_report_helper_command_to_the_hub(agent_module, echo):
    config = tunnel_config(echo.port, command=["openocd", "-f", "secret.cfg"])
    reported = [r for r in agent_module.discover_resources(config) if r["resource_type"] == "tunnel"]
    assert reported and "command" not in reported[0]["metadata"]
    assert reported[0]["metadata"]["port"] == echo.port


def test_agent_tunnel_idle_reaper_closes_unused_tunnels(agent_module, echo):
    router = agent_module.OperationRouter(tunnel_config(echo.port, ))
    router.tunnel.idle_timeout = 0.0
    try:
        assert router.execute(op("open"))["success"]
        assert router.tunnel.reap_idle() == 1
        assert not router.execute(op("write", data_b64=b64(b"x")))["success"]
    finally:
        router.tunnel.close_all()


# ---------------------------------------------------------------- hub


def _tunnel_lab(client, agent_module, port):
    admin = bootstrap(client)
    alice = create_user(client, admin, "alice")
    agent_id, credential = enroll_agent(client, admin)
    ids = heartbeat(
        client,
        agent_id,
        credential,
        [{"resource_key": "tunnel:board-ssh", "resource_type": "tunnel", "display_name": "Board SSH", "metadata": {}}],
    )
    target = agent_target(
        client,
        admin,
        "BOARD-TUNNEL",
        [{"name": "SSH", "capability_type": "tunnel", "agent_id": agent_id, "resource_id": ids["tunnel:board-ssh"]}],
    )
    reservation = reserve(client, alice, target["id"])
    session = open_session(client, alice, reservation["id"], "tunnel")
    router = agent_module.OperationRouter(tunnel_config(port))
    return admin, alice, agent_id, credential, session, reservation, router


def _recv_bytes(ws, expect: int, limit=40) -> bytes:
    got = b""
    for _ in range(limit):
        message = ws.receive()
        if message.get("bytes") is not None:
            got += message["bytes"]
        elif message.get("text"):
            decoded = json.loads(message["text"])
            assert decoded["type"] != "closed", decoded
        if len(got) >= expect:
            return got
    raise AssertionError(f"only got {got!r}")


def test_websocket_tunnel_relays_bytes_end_to_end(tmp_path, monkeypatch, agent_module, echo):
    with api_client(tmp_path, monkeypatch) as (client, _db):
        _admin, alice, agent_id, credential, session, _res, router = _tunnel_lab(client, agent_module, echo.port)
        try:
            with FakeAgent(client, agent_id, credential, router.execute):
                with client.websocket_connect(f"/api/v1/sessions/{session['id']}/tunnel/ws") as ws:
                    ws.send_text(json.dumps({"type": "auth", "token": alice}))
                    assert json.loads(ws.receive_text())["type"] == "ready"
                    assert _recv_bytes(ws, 14) == b"SSH-2.0-fake\r\n"
                    data = bytes(range(32, 120)) * 3
                    ws.send_bytes(data)
                    assert _recv_bytes(ws, len(data)) == data.upper()
        finally:
            router.tunnel.close_all()


def test_websocket_tunnel_announces_when_the_board_hangs_up(tmp_path, monkeypatch, agent_module):
    server = EchoServer(hang_up_after=2)
    try:
        with api_client(tmp_path, monkeypatch) as (client, _db):
            _admin, alice, agent_id, credential, session, _res, router = _tunnel_lab(client, agent_module, server.port)
            try:
                with FakeAgent(client, agent_id, credential, router.execute):
                    with client.websocket_connect(f"/api/v1/sessions/{session['id']}/tunnel/ws") as ws:
                        ws.send_text(json.dumps({"type": "auth", "token": alice}))
                        assert json.loads(ws.receive_text())["type"] == "ready"
                        ws.send_bytes(b"hi")
                        closed = None
                        for _ in range(40):
                            message = ws.receive()
                            if message.get("text"):
                                decoded = json.loads(message["text"])
                                if decoded["type"] == "closed":
                                    closed = decoded
                                    break
                        assert closed and "closed the connection" in closed["reason"]
            finally:
                router.tunnel.close_all()
    finally:
        server.close()


def test_websocket_tunnel_rejects_bad_token_and_other_users(tmp_path, monkeypatch, agent_module, echo):
    with api_client(tmp_path, monkeypatch) as (client, _db):
        admin, _alice, _agent_id, _credential, session, _res, _router = _tunnel_lab(client, agent_module, echo.port)
        with client.websocket_connect(f"/api/v1/sessions/{session['id']}/tunnel/ws") as ws:
            ws.send_text(json.dumps({"type": "auth", "token": "garbage"}))
            assert json.loads(ws.receive_text())["reason"] == "Authentication failed"
            with pytest.raises(WebSocketDisconnect):
                ws.receive_text()
        bob = create_user(client, admin, "bob")
        with client.websocket_connect(f"/api/v1/sessions/{session['id']}/tunnel/ws") as ws:
            ws.send_text(json.dumps({"type": "auth", "token": bob}))
            message = json.loads(ws.receive_text())
            assert message["type"] == "closed" and "owner" in message["reason"].lower()


def test_hub_rejects_malformed_tunnel_writes(tmp_path, monkeypatch, agent_module, echo):
    with api_client(tmp_path, monkeypatch) as (client, _db):
        _admin, alice, agent_id, credential, session, _res, router = _tunnel_lab(client, agent_module, echo.port)
        try:
            with FakeAgent(client, agent_id, credential, router.execute):
                url = f"/api/v1/sessions/{session['id']}/execute"
                bad = client.post(url, json={"operation": "write", "params": {"data_b64": "***"}}, headers=auth(alice))
                assert bad.status_code == 409 and "base64" in bad.text
                huge = client.post(
                    url, json={"operation": "write", "params": {"data_b64": "A" * 90000}}, headers=auth(alice)
                )
                assert huge.status_code == 409
                unsupported = client.post(url, json={"operation": "deploy", "params": {}}, headers=auth(alice))
                assert unsupported.status_code == 409
        finally:
            router.tunnel.close_all()


def test_ending_the_reservation_closes_the_agent_side_tunnel(tmp_path, monkeypatch, agent_module, echo):
    with api_client(tmp_path, monkeypatch) as (client, _db):
        _admin, alice, agent_id, credential, session, reservation, router = _tunnel_lab(client, agent_module, echo.port)
        try:
            with FakeAgent(client, agent_id, credential, router.execute) as fake:
                url = f"/api/v1/sessions/{session['id']}/execute"
                assert client.post(url, json={"operation": "open", "params": {}}, headers=auth(alice)).status_code == 200
                assert "r" in " ".join(router.tunnel._channels) or router.tunnel._channels
                client.post(f"/api/v1/reservations/{reservation['id']}/release", headers=auth(alice))
                for _ in range(50):
                    if not router.tunnel._channels:
                        break
                    threading.Event().wait(0.1)
                assert not router.tunnel._channels
                assert any((seen.get("params") or {}).get("cleanup") for seen in fake.seen)
        finally:
            router.tunnel.close_all()
