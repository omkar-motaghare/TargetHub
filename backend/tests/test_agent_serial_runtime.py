"""Agent serial runtime: ownership, takeover, cleanup, allowlist, buffering and waits."""

from __future__ import annotations

import importlib.util
import os
import pty
import threading
import time
from pathlib import Path

import pytest

RUNTIME_PATH = Path(__file__).resolve().parents[1] / "app" / "web" / "agent" / "targethub_agent.py"


@pytest.fixture(scope="module")
def runtime():
    spec = importlib.util.spec_from_file_location("targethub_agent_serial", RUNTIME_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def pty_pair():
    master, slave = pty.openpty()
    yield master, os.ttyname(slave)
    os.close(master)
    os.close(slave)


def op(path, session, operation, **params):
    return {
        "session_id": session,
        "resource_id": "r1",
        "resource_key": path,
        "resource_type": "serial",
        "resource_metadata": {"path": path},
        "operation": operation,
        "params": params,
    }


def test_new_session_takes_over_port_from_ended_session(runtime, pty_pair):
    master, path = pty_pair
    serial = runtime.SerialRuntime()
    try:
        assert serial.execute(op(path, "s1", "open"))["success"]
        assert serial.execute(op(path, "s2", "open"))["success"]
        # The old session can no longer use the port.
        stale = serial.execute(op(path, "s1", "write", text="x"))
        assert not stale["success"] and "not open" in stale["message"]
        assert serial.execute(op(path, "s2", "write", text="hi"))["success"]
        assert b"hi" in os.read(master, 16)
    finally:
        serial.close_all()


def test_cleanup_close_for_previous_session_does_not_close_new_owner(runtime, pty_pair):
    master, path = pty_pair
    serial = runtime.SerialRuntime()
    try:
        serial.execute(op(path, "s1", "open"))
        serial.execute(op(path, "s2", "open"))
        assert serial.execute(op(path, "s1", "close", cleanup=True))["success"]
        assert serial.execute(op(path, "s2", "write", text="ok"))["success"]
    finally:
        serial.close_all()


def test_disallowed_path_is_refused(runtime):
    serial = runtime.SerialRuntime(allowed_paths=lambda: {"/dev/ttyUSB0"})
    result = serial.execute(op("/dev/sda", "s1", "open"))
    assert not result["success"] and "not allowed" in result["message"]


def test_background_reader_buffers_output_between_reads(runtime, pty_pair):
    master, path = pty_pair
    serial = runtime.SerialRuntime()
    try:
        serial.execute(op(path, "s1", "open"))
        for index in range(20):
            os.write(master, f"line-{index}\n".encode())
        time.sleep(0.5)
        result = serial.execute(op(path, "s1", "read", size=65536, wait_ms=500))
        text = result["data"]["data_text"]
        assert "line-0" in text and "line-19" in text
    finally:
        serial.close_all()


def test_read_with_wait_returns_as_soon_as_data_arrives(runtime, pty_pair):
    master, path = pty_pair
    serial = runtime.SerialRuntime()
    try:
        serial.execute(op(path, "s1", "open"))
        threading.Timer(0.3, lambda: os.write(master, b"late\n")).start()
        started = time.monotonic()
        result = serial.execute(op(path, "s1", "read", size=64, wait_ms=4000))
        assert "late" in result["data"]["data_text"]
        assert time.monotonic() - started < 2
    finally:
        serial.close_all()


def test_write_is_not_blocked_by_a_pending_read(runtime, pty_pair):
    master, path = pty_pair
    serial = runtime.SerialRuntime()
    try:
        serial.execute(op(path, "s1", "open"))
        reader = threading.Thread(target=serial.execute, args=(op(path, "s1", "read", wait_ms=3000),))
        reader.start()
        time.sleep(0.1)
        started = time.monotonic()
        assert serial.execute(op(path, "s1", "write", text="fast"))["success"]
        assert time.monotonic() - started < 0.5
        reader.join(timeout=5)
    finally:
        serial.close_all()


def test_idle_channels_are_reaped(runtime, pty_pair):
    _master, path = pty_pair
    serial = runtime.SerialRuntime(idle_timeout=0)
    serial.execute(op(path, "s1", "open"))
    time.sleep(0.01)
    assert serial.reap_idle() == 1
    assert not serial.execute(op(path, "s1", "write", text="x"))["success"]


def test_virtual_board_answers_commands(runtime):
    serial = runtime.SerialRuntime()
    base = {"resource_key": "sim://board", "resource_metadata": {"simulated": True}}
    payload = {**op("sim://board", "s1", "open"), **base}
    assert serial.execute(payload)["success"]
    banner = serial.execute({**payload, "operation": "read", "params": {"size": 4096}})["data"]["data_text"]
    assert "board>" in banner
    serial.execute({**payload, "operation": "write", "params": {"text": "version\r"}})
    reply = serial.execute({**payload, "operation": "read", "params": {"size": 4096}})["data"]["data_text"]
    assert "TargetHub virtual board" in reply


def test_private_metadata_is_not_reported_to_the_hub(runtime):
    config = {
        "resources": [
            {
                "resource_key": "deploy:flash",
                "resource_type": "deploy",
                "metadata": {"command": ["flash", "{artifact}"], "api_key": "secret", "timeout": 30},
            }
        ]
    }
    reported = [item for item in runtime.discover_resources(config) if item["resource_key"] == "deploy:flash"]
    assert reported[0]["metadata"] == {"timeout": 30}


def test_router_reports_unexpected_errors_instead_of_hanging(runtime, monkeypatch):
    router = runtime.OperationRouter({"resources": []})
    calls = []

    def boom(_payload):
        raise RuntimeError("kaput")

    monkeypatch.setattr(router, "execute", boom)
    monkeypatch.setattr(runtime, "complete_operation", lambda config, **kwargs: calls.append(kwargs))
    runtime.run_operation({}, router, {"id": "op-1"}, 5)
    assert calls and calls[0]["success"] is False and "kaput" in calls[0]["message"]


def test_pyserial_backend_used_on_windows_works_with_a_pty(runtime, pty_pair):
    """The pyserial path (mandatory on Windows) exercised against a real pty."""
    pytest.importorskip("serial")
    assert runtime._pyserial is not None
    master, path = pty_pair
    serial = runtime.SerialRuntime()
    try:
        assert serial.execute(op(path, "s1", "open"))["success"]
        channel = serial._channels["r1"]
        assert type(channel.port).__name__ == "_PySerialPort"
        assert serial.execute(op(path, "s1", "write", text="via-pyserial"))["success"]
        assert b"via-pyserial" in os.read(master, 64)
        os.write(master, b"answer\n")
        assert "answer" in serial.execute(op(path, "s1", "read", wait_ms=2000))["data"]["data_text"]
    finally:
        serial.close_all()
