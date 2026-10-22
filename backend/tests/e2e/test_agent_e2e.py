"""Real end-to-end run: live uvicorn hub + real agent subprocess.

Serial uses a pty pair (loopback echo thread), power uses a fake sysfs GPIO tree and deploy
copies a checksummed artifact. Run with: pytest -m e2e backend/tests/e2e
"""

import hashlib
import json
import os
import pty
import secrets
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
from datetime import UTC, datetime, timedelta
from functools import partial
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path

import httpx
import pytest

pytestmark = pytest.mark.e2e

BACKEND = Path(__file__).resolve().parents[2]
AGENT_SCRIPT = BACKEND / "app" / "web" / "agent" / "targethub_agent.py"
WORK_ROOT = BACKEND.parent / ".e2e"
BOOTSTRAP_TOKEN = "e2e-bootstrap-" + secrets.token_hex(8)
OFFLINE_AFTER = 8


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def wait_until(predicate, timeout: float, message: str, interval: float = 0.2):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(interval)
    raise AssertionError(f"timed out waiting for: {message}")


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *args):
        return None


def tail(path: Path, lines: int = 30) -> str:
    return "\n".join(path.read_text(errors="replace").splitlines()[-lines:]) if path.exists() else ""


class Lab:
    """Holds the processes and fixtures of one E2E run."""

    def __init__(self, work: Path):
        self.work = work
        self.port = free_port()
        self.base = f"http://127.0.0.1:{self.port}"
        self.api = f"{self.base}/api/v1"
        self.gpio_base = work / "gpio"
        self.gpio_value = self.gpio_base / "gpio17" / "value"
        self.flashed = work / "flashed.bin"
        self.processes: list[subprocess.Popen] = []
        self.agent: subprocess.Popen | None = None
        self.stop_echo = threading.Event()
        self.http = httpx.Client(timeout=60)

    def spawn(self, name: str, args: list[str], env: dict, cwd: Path) -> subprocess.Popen:
        log = (self.work / f"{name}.log").open("w")
        proc = subprocess.Popen(args, env=env, cwd=cwd, stdout=log, stderr=subprocess.STDOUT)
        self.processes.append(proc)
        return proc

    def start_hub(self):
        env = {
            **os.environ,
            "SECRET_KEY": secrets.token_hex(32),
            "ENVIRONMENT": "production",
            "DATABASE_URL": os.environ.get(
                "TARGETHUB_TEST_DATABASE_URL", f"sqlite:///{self.work / 'hub.sqlite3'}"
            ),
            "ADMIN_BOOTSTRAP_TOKEN": BOOTSTRAP_TOKEN,
            "TARGETHUB_PUBLIC_URL": self.base,
            "TARGETHUB_AGENT_OFFLINE_AFTER_SECONDS": str(OFFLINE_AFTER),
        }
        migrate = subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            env=env, cwd=BACKEND, capture_output=True, text=True,
        )
        assert migrate.returncode == 0, migrate.stderr
        self.spawn(
            "hub",
            [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1",
             "--port", str(self.port), "--log-level", "warning"],
            env, BACKEND,
        )
        wait_until(lambda: self._hub_ready(), 30, "hub readiness")

    def _hub_ready(self) -> bool:
        try:
            return self.http.get(f"{self.base}/health/ready", timeout=2).status_code == 200
        except httpx.HTTPError:
            return False

    def start_agent(self):
        self.agent = self.spawn(
            "agent",
            [sys.executable, str(AGENT_SCRIPT), "--config", str(self.work / "agent.json")],
            {**os.environ}, self.work,
        )

    def echo_loop(self, master: int):
        import select

        while not self.stop_echo.is_set():
            ready, _, _ = select.select([master], [], [], 0.2)
            if not ready:
                continue
            try:
                data = os.read(master, 1024)
            except OSError:
                return
            os.write(master, b"ECHO:" + data.replace(b"\n", b"\r\n"))

    def call(self, method: str, path: str, token: str | None = None, **kwargs) -> httpx.Response:
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        return self.http.request(method, f"{self.api}{path}", headers=headers, **kwargs)

    def login(self, username: str, password: str) -> str:
        response = self.call("POST", "/auth/token", data={"username": username, "password": password})
        assert response.status_code == 200, response.text
        return response.json()["access_token"]

    def shutdown(self):
        self.stop_echo.set()
        for proc in self.processes:
            if proc.poll() is None:
                proc.kill()
                proc.wait(timeout=10)
        self.http.close()


@pytest.fixture(scope="module")
def lab():
    WORK_ROOT.mkdir(exist_ok=True)
    work = WORK_ROOT / f"run-{os.getpid()}"
    work.mkdir()
    env = Lab(work)
    master, slave = pty.openpty()
    serial_path = os.ttyname(slave)
    env.serial_path = serial_path

    line_dir = env.gpio_base / "gpio17"
    line_dir.mkdir(parents=True)
    (line_dir / "value").write_text("0")
    (line_dir / "direction").write_text("in")
    (env.gpio_base / "export").write_text("")

    artifact_dir = work / "artifacts"
    artifact_dir.mkdir()
    payload = b"e2e-firmware" * 512
    (artifact_dir / "fw.bin").write_bytes(payload)
    artifact_server = HTTPServer(("127.0.0.1", 0), partial(QuietHandler, directory=str(artifact_dir)))
    threading.Thread(target=artifact_server.serve_forever, daemon=True).start()
    env.artifact_url = f"http://127.0.0.1:{artifact_server.server_port}/fw.bin"
    env.artifact_sha = hashlib.sha256(payload).hexdigest()

    threading.Thread(target=env.echo_loop, args=(master,), daemon=True).start()
    try:
        env.start_hub()
        yield env
    except Exception:
        print("--- hub log ---\n" + tail(work / "hub.log"))
        print("--- agent log ---\n" + tail(work / "agent.log"))
        raise
    finally:
        env.shutdown()
        artifact_server.shutdown()
        os.close(master)
        os.close(slave)
        shutil.rmtree(work, ignore_errors=True)


def agent_config(lab: Lab, token: str) -> dict:
    return {
        "targethub_url": lab.base,
        "allow_insecure_http": True,
        "enrollment_token": token,
        "heartbeat_interval": 5,
        "operation_poll_wait_seconds": 1,
        "request_timeout": 15,
        "resources": [
            {
                "resource_key": lab.serial_path,
                "resource_type": "serial",
                "display_name": "pty console",
                "metadata": {"path": lab.serial_path, "baudrate": 115200, "timeout": 0.5},
            },
            {
                "resource_key": "power:relay1",
                "resource_type": "power",
                "display_name": "Relay 1 (active-low)",
                "metadata": {
                    "backend": "sysfs", "gpio_base": str(lab.gpio_base), "line": 17,
                    "active_low": True, "pulse_seconds": 0.3,
                },
            },
            {
                "resource_key": "deploy:flash",
                "resource_type": "deploy",
                "display_name": "Flash by copy",
                "metadata": {"command": ["cp", "{artifact}", str(lab.flashed)], "allow_http": True},
            },
        ],
    }


def test_full_lab_flow(lab: Lab):
    # --- hub bootstrap, users, enrollment
    boot = lab.call("POST", "/auth/bootstrap", json={
        "username": "admin", "password": "admin-e2e-pass", "bootstrap_token": BOOTSTRAP_TOKEN})
    assert boot.status_code in (200, 201), boot.text
    admin = lab.login("admin", "admin-e2e-pass")
    for name in ("alice", "bob"):
        created = lab.call("POST", "/auth/users", admin,
                           json={"username": name, "password": f"{name}-e2e-pass", "roles": ["user"]})
        assert created.status_code == 200, created.text
    alice, bob = lab.login("alice", "alice-e2e-pass"), lab.login("bob", "bob-e2e-pass")

    enrollment = lab.call("POST", "/agents/enrollments", admin, json={"agent_name": "e2e-pi"}).json()
    assert "sha256sum -c" in enrollment["install_command"]

    # --- agent enrolls and heartbeats with its resources
    (lab.work / "agent.json").write_text(json.dumps(agent_config(lab, enrollment["token"])))
    lab.start_agent()

    def agent_online():
        agents = lab.call("GET", "/agents", admin).json()
        online = [a for a in agents if a["status"] == "online" and len(a["resources"]) >= 3]
        return online[0] if online else None

    agent = wait_until(agent_online, 40, "agent online with resources")
    resources = {r["resource_key"]: r for r in agent["resources"]}
    assert {"power:relay1", "deploy:flash", lab.serial_path} <= resources.keys()
    saved = json.loads((lab.work / "agent.json").read_text())
    assert "enrollment_token" not in saved and saved["credential"]
    assert oct((lab.work / "agent.json").stat().st_mode & 0o777) == "0o600"

    # --- target with serial/power/deploy capabilities mapped to the agent
    def capability(name, kind, key, config=None):
        return {"name": name, "capability_type": kind, "agent_id": agent["id"],
                "resource_id": resources[key]["id"], "provider_key": f"{kind}.e2e",
                "provider_config": config or {}}

    target = lab.call("POST", "/targets", admin, json={
        "name": "PI-BOARD-1",
        "capabilities": [
            capability("Console", "serial", lab.serial_path),
            capability("Relay", "power", "power:relay1", {"transport": "agent"}),
            capability("Flasher", "deploy", "deploy:flash", {"transport": "agent"}),
        ],
    })
    assert target.status_code == 201, target.text
    target_id = target.json()["id"]

    # --- reservation exclusivity
    now = datetime.now(UTC)
    window = {"target_id": target_id, "starts_at": now.isoformat(),
              "ends_at": (now + timedelta(hours=1)).isoformat()}
    reservation = lab.call("POST", "/reservations", alice, json={**window, "user_id": "alice"})
    assert reservation.status_code == 201, reservation.text
    reservation_id = reservation.json()["id"]
    conflict = lab.call("POST", "/reservations", bob, json={**window, "user_id": "bob"})
    assert conflict.status_code == 409, conflict.text

    def open_session(capability_type, token=alice, user="alice", reservation=reservation_id):
        return lab.call("POST", "/sessions", token, json={
            "reservation_id": reservation, "user_id": user, "capability_type": capability_type})

    assert open_session("serial", bob, "bob").status_code in (403, 409)

    def execute(session_id, operation, params=None, token=alice):
        response = lab.call("POST", f"/sessions/{session_id}/execute", token,
                            json={"operation": operation, "params": params or {}})
        return response

    # --- serial over pty through the agent
    serial = open_session("serial")
    assert serial.status_code == 201, serial.text
    serial_id = serial.json()["id"]
    assert execute(serial_id, "open").status_code == 200
    assert execute(serial_id, "write", {"text": "hello-e2e\n"}).status_code == 200
    seen = ""

    def got_echo():
        nonlocal seen
        result = execute(serial_id, "read", {"size": 256})
        assert result.status_code == 200, result.text
        seen += result.json()["data"]["data_text"]
        return "ECHO:hello-e2e" in seen

    wait_until(got_echo, 20, "serial echo through pty")
    assert execute(serial_id, "write", {"text": "x"}, token=bob).status_code in (403, 409)

    # the terminal UI uses the dedicated serial endpoints
    assert lab.call("POST", f"/sessions/{serial_id}/serial/write", alice, json={"text": "ui-line\n"}).status_code == 200
    ui_seen = ""

    def got_ui_echo():
        nonlocal ui_seen
        read = lab.call("GET", f"/sessions/{serial_id}/serial/read", alice, params={"size": 256})
        assert read.status_code == 200, read.text
        assert "provider_key" not in read.json()
        ui_seen += read.json()["data"]["data_text"]
        return "ECHO:ui-line" in ui_seen

    wait_until(got_ui_echo, 20, "serial echo via /serial endpoints")

    # --- power through fake GPIO (active-low relay: ON drives the line to 0)
    power = open_session("power")
    assert power.status_code == 201, power.text
    power_id = power.json()["id"]
    assert execute(power_id, "off").status_code == 200
    assert lab.gpio_value.read_text() == "1"
    assert execute(power_id, "on").status_code == 200
    assert lab.gpio_value.read_text() == "0"
    status = execute(power_id, "status")
    assert status.status_code == 200 and status.json()["data"]["state"] == "on"
    cycle = execute(power_id, "cycle")
    assert cycle.status_code == 200 and cycle.json()["data"]["state"] == "on"
    assert lab.gpio_value.read_text() == "0"
    assert execute(power_id, "reset").status_code == 200
    assert execute(power_id, "off").status_code == 200
    assert lab.gpio_value.read_text() == "1"

    # --- the Python SDK and CLI drive the same hub
    sys.path.insert(0, str(BACKEND.parent / "sdk" / "python"))
    from targethub_sdk import TargetHubClient

    with TargetHubClient(lab.base, alice) as sdk:
        assert sdk.me()["username"] == "alice"
        assert {"on", "off", "status"} <= set(sdk.operations(power_id))
        assert sdk.power(power_id, "on")["data"]["state"] == "on"
    assert lab.gpio_value.read_text() == "0"
    cli_run = subprocess.run(
        [sys.executable, "-m", "targethub_sdk.cli", "--url", lab.base, "power", power_id, "off"],
        env={**os.environ, "TARGETHUB_TOKEN": alice, "PYTHONPATH": str(BACKEND.parent / "sdk" / "python")},
        capture_output=True, text=True, timeout=60,
    )
    assert cli_run.returncode == 0, cli_run.stderr
    assert json.loads(cli_run.stdout)["data"]["state"] == "off"
    assert lab.gpio_value.read_text() == "1"

    # --- deploy: checksum enforced end to end
    deploy = open_session("deploy")
    assert deploy.status_code == 201, deploy.text
    deploy_id = deploy.json()["id"]
    bad = execute(deploy_id, "deploy", {"url": lab.artifact_url, "sha256": "0" * 64})
    assert bad.status_code == 409 and "mismatch" in bad.text
    assert not lab.flashed.exists()
    good = execute(deploy_id, "deploy", {"url": lab.artifact_url, "sha256": lab.artifact_sha})
    assert good.status_code == 200, good.text
    assert hashlib.sha256(lab.flashed.read_bytes()).hexdigest() == lab.artifact_sha

    # --- audit trail and metrics
    audit = lab.call("GET", "/audit", admin)
    assert audit.status_code == 200
    assert any(entry["action"] == "provider.execute" for entry in audit.json())
    assert "targethub_provider_operations_total" in lab.http.get(f"{lab.base}/metrics").text

    # --- releasing the reservation ends sessions; bob can now reserve
    released = lab.call("POST", f"/reservations/{reservation_id}/release", alice, params={"user_id": "alice"})
    assert released.status_code == 200, released.text
    assert execute(serial_id, "read").status_code == 409
    assert lab.call("POST", "/reservations", bob, json={**window, "user_id": "bob"}).status_code == 201

    # --- graceful SIGTERM, restart with persisted credential (no re-enroll)
    assert lab.agent is not None
    lab.agent.send_signal(signal.SIGTERM)
    assert lab.agent.wait(timeout=20) == 0
    lab.start_agent()
    wait_until(agent_online, 40, "agent online again after restart")
    assert "Enrolled Agent" not in tail(lab.work / "agent.log", 200)

    # --- hard kill -> hub marks the agent offline
    lab.agent.kill()
    lab.agent.wait(timeout=10)
    wait_until(
        lambda: lab.call("GET", "/agents", admin).json()[0]["status"] == "offline",
        OFFLINE_AFTER + 20, "agent offline detection",
    )
