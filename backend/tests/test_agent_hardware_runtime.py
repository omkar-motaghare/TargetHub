import hashlib
import importlib.util
import os
import pty
import stat
import threading
import time
from functools import partial
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path

import pytest

RUNTIME_PATH = (
    Path(__file__).resolve().parents[1] / "app" / "web" / "agent" / "targethub_agent.py"
)


@pytest.fixture(scope="module")
def runtime():
    spec = importlib.util.spec_from_file_location("targethub_agent_hw", RUNTIME_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def make_gpio_tree(base: Path, line: int) -> Path:
    line_dir = base / f"gpio{line}"
    line_dir.mkdir(parents=True)
    (line_dir / "value").write_text("0")
    (line_dir / "direction").write_text("in")
    (base / "export").write_text("")
    return line_dir


def power_metadata(base: Path, **extra) -> dict:
    return {"backend": "sysfs", "gpio_base": str(base), "line": 17, "pulse_seconds": 0.05, **extra}


def test_sysfs_power_on_off_status_active_high(runtime, tmp_path):
    line_dir = make_gpio_tree(tmp_path, 17)
    power = runtime.PowerRuntime()
    meta = power_metadata(tmp_path)

    assert power.execute("on", meta)["success"]
    assert (line_dir / "value").read_text() == "1"
    assert (line_dir / "direction").read_text() == "high"
    assert power.execute("status", meta)["data"]["state"] == "on"
    assert power.execute("off", meta)["success"]
    assert (line_dir / "value").read_text() == "0"
    assert power.execute("status", meta)["data"]["state"] == "off"


def test_sysfs_power_active_low_inverts_levels(runtime, tmp_path):
    line_dir = make_gpio_tree(tmp_path, 17)
    power = runtime.PowerRuntime()
    meta = power_metadata(tmp_path, active_low=True)

    power.execute("on", meta)
    assert (line_dir / "value").read_text() == "0"
    assert power.execute("status", meta)["data"]["state"] == "on"
    power.execute("off", meta)
    assert (line_dir / "value").read_text() == "1"


def test_power_cycle_ends_on_and_records_off_then_on(runtime, tmp_path):
    line_dir = make_gpio_tree(tmp_path, 17)
    writes: list[str] = []
    gpio = runtime.SysfsGpio(str(tmp_path))
    original = gpio.write

    def spy(line, level):
        writes.append(str(level))
        original(line, level)

    gpio.write = spy
    power = runtime.PowerRuntime()
    power._backend = lambda _metadata: gpio
    result = power.execute("cycle", power_metadata(tmp_path))
    assert result["success"] and result["data"]["state"] == "on"
    assert writes == ["0", "1"]
    assert (line_dir / "value").read_text() == "1"


def test_reset_line_pulse_ends_deasserted(runtime, tmp_path):
    line_dir = make_gpio_tree(tmp_path, 17)
    power = runtime.PowerRuntime()
    result = power.execute("reset", power_metadata(tmp_path, kind="reset_line", active_low=True))
    assert result["success"] and result["data"]["state"] == "off"
    assert (line_dir / "value").read_text() == "1"


def test_power_rejects_bad_config_and_operation(runtime, tmp_path):
    power = runtime.PowerRuntime()
    assert not power.execute("on", {"backend": "sysfs"})["success"]
    assert not power.execute("on", {"backend": "nope", "line": 1})["success"]
    make_gpio_tree(tmp_path, 17)
    assert not power.execute("explode", power_metadata(tmp_path))["success"]


def test_gpiod_backend_holds_line_with_gpioset_process(runtime, tmp_path, monkeypatch):
    log = tmp_path / "gpioset.log"
    script = tmp_path / "gpioset"
    script.write_text(f"#!/bin/sh\necho \"$@\" >> {log}\nexec sleep 30\n")
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", f"{tmp_path}:{os.environ['PATH']}")

    power = runtime.PowerRuntime()
    meta = {"backend": "gpiod", "chip": "gpiochip4", "line": 23, "active_low": True}

    def wait_for_lines(count: int) -> None:
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline and not (log.exists() and len(log.read_text().splitlines()) >= count):
            time.sleep(0.05)

    assert power.execute("on", meta)["success"]
    wait_for_lines(1)
    assert power.execute("off", meta)["success"]
    wait_for_lines(2)
    assert log.read_text().splitlines() == ["--chip gpiochip4 23=0", "--chip gpiochip4 23=1"]
    assert power.execute("status", meta)["data"]["state"] == "off"
    for gpio in power._gpiod.values():
        gpio._release(23)


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *args):
        return None


@pytest.fixture
def artifact_server(tmp_path):
    served = tmp_path / "served"
    served.mkdir()
    payload = b"firmware-bytes" * 100
    (served / "fw.bin").write_bytes(payload)
    server = HTTPServer(("127.0.0.1", 0), partial(QuietHandler, directory=str(served)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_port}/fw.bin", hashlib.sha256(payload).hexdigest()
    server.shutdown()
    server.server_close()


def test_deploy_verifies_checksum_then_runs_configured_command(runtime, tmp_path, artifact_server):
    url, digest = artifact_server
    out = tmp_path / "flashed.bin"
    meta = {"command": ["cp", "{artifact}", str(out)], "allow_http": True}
    deploy = runtime.DeployRuntime()

    result = deploy.execute("deploy", {"url": url, "sha256": digest}, meta)
    assert result["success"], result
    assert hashlib.sha256(out.read_bytes()).hexdigest() == digest
    assert deploy.execute("status", {}, meta)["data"]["status"] == "ok"


def test_deploy_refuses_checksum_mismatch_and_plain_http(runtime, tmp_path, artifact_server):
    url, digest = artifact_server
    out = tmp_path / "flashed.bin"
    meta = {"command": ["cp", "{artifact}", str(out)], "allow_http": True}
    deploy = runtime.DeployRuntime()

    mismatch = deploy.execute("deploy", {"url": url, "sha256": "0" * 64}, meta)
    assert not mismatch["success"] and "mismatch" in mismatch["message"]
    assert not out.exists()

    refused = deploy.execute("deploy", {"url": url, "sha256": digest}, {"command": ["true"]})
    assert not refused["success"] and "https" in refused["message"]


def test_router_uses_local_config_not_hub_supplied_metadata(runtime, tmp_path):
    line_dir = make_gpio_tree(tmp_path, 17)
    local = power_metadata(tmp_path)
    router = runtime.OperationRouter(
        {"resources": [{"resource_key": "power:relay1", "resource_type": "power", "metadata": local}]}
    )
    payload = {
        "resource_type": "power",
        "resource_key": "power:relay1",
        "operation": "on",
        "resource_metadata": {"backend": "sysfs", "gpio_base": "/etc", "line": 1},
    }
    assert router.execute(payload)["success"]
    assert (line_dir / "value").read_text() == "1"

    unknown = router.execute({**payload, "resource_key": "power:other"})
    assert not unknown["success"] and "not configured" in unknown["message"]


def test_serial_runtime_real_pty_roundtrip(runtime):
    master, slave = pty.openpty()
    path = os.ttyname(slave)
    serial = runtime.SerialRuntime()
    base = {
        "session_id": "s1",
        "resource_id": "r1",
        "resource_key": path,
        "resource_metadata": {"path": path, "timeout": 1.0},
    }
    try:
        assert serial.execute({**base, "operation": "open"})["success"]
        written = serial.execute({**base, "operation": "write", "params": {"text": "ping\n"}})
        assert written["success"]
        assert b"ping" in os.read(master, 64)
        os.write(master, b"pong\r\n")
        read = serial.execute({**base, "operation": "read", "params": {"size": 64}})
        assert "pong" in read["data"]["data_text"]
        assert serial.execute({**base, "operation": "close"})["success"]
    finally:
        serial.close_all()
        os.close(master)
        os.close(slave)
