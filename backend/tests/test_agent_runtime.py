import importlib.util
import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import sys

import pytest


def _load_runtime_module():
    runtime_path = (
        Path(__file__).resolve().parents[1]
        / "app"
        / "web"
        / "agent"
        / "targethub_agent.py"
    )
    spec = importlib.util.spec_from_file_location("targethub_agent_runtime", runtime_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_runtime_enroll_then_heartbeat_with_fake_server(tmp_path):
    runtime = _load_runtime_module()
    events: list[tuple[str, dict, dict]] = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            headers = {k: v for k, v in self.headers.items()}
            events.append((self.path, payload, headers))

            if self.path == "/api/v1/agents/enroll":
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(
                    json.dumps(
                        {
                            "agent": {"id": "agent-123"},
                            "credential": "agent-secret-credential",
                        }
                    ).encode("utf-8")
                )
                return

            if self.path == "/api/v1/agents/agent-123/heartbeat":
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"status": "ok"}).encode("utf-8"))
                return

            self.send_response(404)
            self.end_headers()

        def log_message(self, *_args, **_kwargs):
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        base_url = f"http://127.0.0.1:{server.server_port}"
        config_path = tmp_path / "agent.json"
        config = {
            "targethub_url": base_url,
            "enrollment_token": "enroll-token-abc",
            "heartbeat_interval": 15,
            "resources": [
                {
                    "resource_key": "custom-resource-1",
                    "resource_type": "custom",
                    "display_name": "custom-resource-1",
                    "metadata": {"kind": "fixture"},
                    "available": True,
                }
            ],
        }
        runtime.save_config(config_path, config)

        loaded = runtime.load_config(config_path)
        runtime.enroll(loaded, config_path, request_timeout=5)
        assert loaded.get("enrollment_token") is None
        assert loaded["agent_id"] == "agent-123"
        assert loaded["credential"] == "agent-secret-credential"

        persisted = runtime.load_config(config_path)
        assert "enrollment_token" not in persisted
        assert persisted["credential"] == "agent-secret-credential"

        runtime.heartbeat(persisted, request_timeout=5)

        enroll_events = [item for item in events if item[0] == "/api/v1/agents/enroll"]
        heartbeat_events = [item for item in events if item[0] == "/api/v1/agents/agent-123/heartbeat"]
        assert len(enroll_events) == 1
        assert len(heartbeat_events) == 1
        assert str(heartbeat_events[0][2].get("Authorization", "")).startswith("Bearer ")
        assert any(r["resource_key"] == "custom-resource-1" for r in heartbeat_events[0][1]["resources"])
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_runtime_restart_resumes_from_persisted_credential_without_reenrolling(tmp_path):
    """A process restart must reuse persisted credentials without re-enrollment."""
    runtime = _load_runtime_module()
    events: list[tuple[str, dict, dict]] = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            headers = {k: v for k, v in self.headers.items()}
            events.append((self.path, payload, headers))
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"status": "ok"}).encode("utf-8"))

        def log_message(self, *_args, **_kwargs):
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        base_url = f"http://127.0.0.1:{server.server_port}"
        config_path = tmp_path / "agent.json"
        runtime.save_config(
            config_path,
            {
                "targethub_url": base_url,
                "agent_id": "agent-123",
                "credential": "agent-secret-credential",
                "heartbeat_interval": 15,
            },
        )

        restarted_config = runtime.load_config(config_path)
        assert "enrollment_token" not in restarted_config
        runtime.heartbeat(restarted_config, request_timeout=5)

        enroll_events = [item for item in events if item[0] == "/api/v1/agents/enroll"]
        heartbeat_events = [item for item in events if item[0] == "/api/v1/agents/agent-123/heartbeat"]
        assert len(enroll_events) == 0
        assert len(heartbeat_events) == 1
        assert str(heartbeat_events[0][2].get("Authorization", "")).startswith("Bearer ")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_runtime_operation_poll_and_complete_protocol():
    runtime = _load_runtime_module()
    events: list[tuple[str, dict, dict]] = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            headers = {k: v for k, v in self.headers.items()}
            events.append((self.path, payload, headers))

            if self.path == "/api/v1/agents/agent-123/operations/poll":
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(
                    json.dumps(
                        {
                            "operation": {
                                "id": "op-1",
                                "session_id": "session-1",
                                "resource_id": "resource-1",
                                "resource_key": "sim://uart0",
                                "resource_type": "serial",
                                "resource_metadata": {"simulated": True},
                                "operation": "read",
                                "params": {"size": 8},
                                "requested_at": "2026-01-01T00:00:00Z",
                            }
                        }
                    ).encode("utf-8")
                )
                return

            if self.path == "/api/v1/agents/agent-123/operations/op-1/complete":
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(
                    json.dumps({"status": "completed", "operation_id": "op-1"}).encode("utf-8")
                )
                return

            self.send_response(404)
            self.end_headers()

        def log_message(self, *_args, **_kwargs):
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        base_url = f"http://127.0.0.1:{server.server_port}"
        config = {
            "targethub_url": base_url,
            "agent_id": "agent-123",
            "credential": "agent-secret-credential",
        }
        polled = runtime.poll_operation(config, wait_seconds=1, request_timeout=5)
        assert polled["operation"]["id"] == "op-1"

        completed = runtime.complete_operation(
            config,
            operation_id="op-1",
            success=True,
            message="ok",
            data={"bytes_read": 1},
            request_timeout=5,
        )
        assert completed["status"] == "completed"

        poll_events = [item for item in events if item[0].endswith("/operations/poll")]
        complete_events = [item for item in events if item[0].endswith("/operations/op-1/complete")]
        assert len(poll_events) == 1
        assert len(complete_events) == 1
        assert str(poll_events[0][2].get("Authorization", "")).startswith("Bearer ")
        assert str(complete_events[0][2].get("Authorization", "")).startswith("Bearer ")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_serial_runtime_simulated_transport_roundtrip():
    runtime = _load_runtime_module()
    serial_runtime = runtime.SerialRuntime()
    payload = {
        "session_id": "s1",
        "resource_id": "r1",
        "resource_key": "sim://uart0",
        "resource_type": "serial",
        "resource_metadata": {"simulated": True},
    }

    opened = serial_runtime.execute({**payload, "operation": "open", "params": {}})
    assert opened["success"] is True

    wrote = serial_runtime.execute(
        {**payload, "operation": "write", "params": {"text": "hello"}}
    )
    assert wrote["success"] is True
    assert wrote["data"]["bytes_written"] == 5

    read = serial_runtime.execute({**payload, "operation": "read", "params": {"size": 4096}})
    assert read["success"] is True
    assert "hello" in read["data"]["data_text"]

    closed = serial_runtime.execute({**payload, "operation": "close", "params": {}})
    assert closed["success"] is True


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX file modes")
def test_save_config_writes_mode_0600(tmp_path):
    runtime = _load_runtime_module()
    path = tmp_path / "agent.json"
    runtime.save_config(path, {"targethub_url": "http://example.local"})
    mode = os.stat(path).st_mode & 0o777
    assert mode == 0o600


def test_enroll_does_not_spend_token_when_config_is_unwritable(tmp_path, monkeypatch):
    runtime = _load_runtime_module()
    calls = []
    monkeypatch.setattr(runtime, "api_request", lambda *args, **kwargs: calls.append(args))

    def refuse(path, config):
        raise PermissionError("read-only")

    monkeypatch.setattr(runtime, "save_config", refuse)
    config = {"targethub_url": "http://hub.local", "enrollment_token": "enroll_x"}
    with pytest.raises(PermissionError):
        runtime.enroll(config, tmp_path / "agent.json")
    assert calls == []
    assert config["enrollment_token"] == "enroll_x"
