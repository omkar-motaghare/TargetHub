import hashlib
import os
import shutil
import stat
import subprocess
import threading
from functools import partial
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path

import pytest

APP_DIR = Path(__file__).resolve().parents[1] / "app"
AGENT_DIR = APP_DIR / "web" / "agent"
INSTALL_SH = AGENT_DIR / "install.sh"
TOKEN = "enroll_" + "a" * 32

pytestmark = pytest.mark.skipif(
    shutil.which("curl") is None or shutil.which("sha256sum") is None,
    reason="installer needs curl and sha256sum",
)


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *args):
        return None


@pytest.fixture
def hub_url():
    server = HTTPServer(("127.0.0.1", 0), partial(QuietHandler, directory=str(APP_DIR)))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()
    server.server_close()


def run_installer(prefix, *args):
    return subprocess.run(
        ["bash", str(INSTALL_SH), "--prefix", str(prefix), *args],
        capture_output=True,
        text=True,
        timeout=60,
        env={**os.environ, "HOME": str(prefix)},
    )


def agent_sha() -> str:
    return hashlib.sha256((AGENT_DIR / "targethub_agent.py").read_bytes()).hexdigest()


def test_installer_stages_verified_agent_without_root(tmp_path, hub_url):
    result = run_installer(
        tmp_path,
        "--targethub-url", hub_url,
        "--enrollment-token", TOKEN,
        "--agent-sha256", agent_sha(),
        "--allow-insecure-http",
    )
    assert result.returncode == 0, result.stderr
    agent = tmp_path / "opt/targethub-agent/targethub_agent.py"
    assert agent.read_bytes() == (AGENT_DIR / "targethub_agent.py").read_bytes()
    configs = list((tmp_path / "etc/targethub-agent").glob("*.json"))
    assert len(configs) == 1
    assert stat.S_IMODE(configs[0].stat().st_mode) == 0o600
    unit = (tmp_path / "etc/systemd/system/targethub-agent@.service").read_text()
    assert "User=targethub" in unit and "ProtectSystem=strict" in unit
    assert "NoNewPrivileges=true" in unit


def test_installer_rejects_tampered_checksum(tmp_path, hub_url):
    result = run_installer(
        tmp_path,
        "--targethub-url", hub_url,
        "--enrollment-token", TOKEN,
        "--agent-sha256", "0" * 64,
        "--allow-insecure-http",
    )
    assert result.returncode != 0
    assert "checksum mismatch" in result.stderr
    assert not (tmp_path / "opt/targethub-agent/targethub_agent.py").exists()
    assert not list((tmp_path / "etc/targethub-agent").glob("*.json"))


def test_installer_refuses_plain_http_by_default(tmp_path, hub_url):
    result = run_installer(
        tmp_path,
        "--targethub-url", hub_url,
        "--enrollment-token", TOKEN,
        "--agent-sha256", agent_sha(),
    )
    assert result.returncode == 2
    assert "https" in result.stderr


def test_installer_requires_checksum(tmp_path, hub_url):
    result = run_installer(
        tmp_path,
        "--targethub-url", hub_url,
        "--enrollment-token", TOKEN,
        "--allow-insecure-http",
    )
    assert result.returncode == 2
