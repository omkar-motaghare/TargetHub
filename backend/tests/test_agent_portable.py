"""Agent behaviour that must hold on every supported host OS (Linux, Raspberry Pi, Windows).

No pty, termios or GPIO: these tests also run on the Windows CI runner.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

AGENT = Path(__file__).resolve().parents[1] / "app" / "web" / "agent" / "targethub_agent.py"


@pytest.fixture(scope="module")
def agent():
    spec = importlib.util.spec_from_file_location("targethub_agent_portable", AGENT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Quiet(SimpleHTTPRequestHandler):
    def log_message(self, *args):
        return None


@pytest.fixture
def artifact_server(tmp_path):
    (tmp_path / "fw.bin").write_bytes(b"firmware-v1")
    server = ThreadingHTTPServer(("127.0.0.1", 0), partial(Quiet, directory=str(tmp_path)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_port}/fw.bin", hashlib.sha256(b"firmware-v1").hexdigest()
    server.shutdown()
    server.server_close()


def test_platform_is_supported(agent):
    agent.ensure_supported_platform()


def test_simulated_board_console_through_router(agent):
    router = agent.OperationRouter({"resources": []})
    base = {"session_id": "s1", "resource_id": "r1", "resource_key": "sim://board", "resource_type": "serial",
            "resource_metadata": {"simulated": True}}
    assert router.execute({**base, "operation": "open", "params": {}})["success"]
    assert router.execute({**base, "operation": "write", "params": {"text": "hello\n"}})["success"]
    read = router.execute({**base, "operation": "read", "params": {"size": 4096, "wait_ms": 1000}})
    assert read["success"] and "hello" in read["data"]["data_text"]
    assert router.execute({**base, "operation": "close", "params": {}})["success"]


def test_unknown_serial_path_is_refused(agent):
    router = agent.OperationRouter({"resources": []})
    result = router.execute({"session_id": "s1", "resource_id": "r1", "resource_key": "COM99",
                             "resource_type": "serial", "operation": "open", "params": {}})
    assert result["success"] is False


def test_power_and_deploy_need_local_configuration(agent):
    router = agent.OperationRouter({"resources": []})
    for kind in ("power", "deploy"):
        result = router.execute({"resource_key": f"{kind}:x", "resource_type": kind, "operation": "status"})
        assert result == {"success": False, "message": "Resource is not configured on this Agent"}


def test_deploy_runs_configured_command_after_checksum(agent, artifact_server, tmp_path):
    url, sha = artifact_server
    target = tmp_path / "flashed.bin"
    copy = f"import shutil,sys; shutil.copy(sys.argv[1], {str(target)!r})"
    config = {"resources": [{"resource_key": "deploy:flash", "resource_type": "deploy",
                             "metadata": {"command": [sys.executable, "-c", copy, "{artifact}"], "allow_http": True}}]}
    router = agent.OperationRouter(config)
    payload = {"resource_key": "deploy:flash", "resource_type": "deploy", "operation": "deploy"}

    bad = router.execute({**payload, "params": {"url": url, "sha256": "0" * 64}})
    assert bad["success"] is False and "mismatch" in bad["message"] and not target.exists()

    ok = router.execute({**payload, "params": {"url": url, "sha256": sha}})
    assert ok["success"], ok
    assert target.read_bytes() == b"firmware-v1"


def test_config_round_trip(agent, tmp_path):
    path = tmp_path / "nested" / "agent.json"
    agent.save_config(path, {"targethub_url": "https://hub.example", "resources": []})
    assert json.loads(path.read_text())["targethub_url"] == "https://hub.example"
    assert agent.load_config(path)["targethub_url"] == "https://hub.example"
