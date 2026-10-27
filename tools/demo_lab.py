#!/usr/bin/env python3
"""Start a complete simulated lab against a running TargetHub server.

What it does (Windows, Linux, macOS, Raspberry Pi):
  1. Starts the mock DD power server (tools/simulators/dd_mock_server.py).
  2. On Linux/macOS starts a virtual board on a pty that boots whenever its DD
     relay turns ON (tools/simulators/virtual_board.py). On Windows the Agent's
     built-in sim:// board is used instead.
  3. Enrolls and starts a local TargetHub Agent exposing that serial console.
  4. Creates demo targets:
       DEMO-BOARD-01  serial (Agent) + DD power (server-hosted), tags demo,virtual
       DEMO-POWER-02  DD power only (no Agent at all),              tags demo,power-only
  5. Prints what to click, and keeps everything running until Ctrl+C.

Requirements: a TargetHub server you can reach (docker compose up, or
`uvicorn app.main:app` in backend/), and an admin account. If the server has no
users yet and you pass --bootstrap-token, the admin is created for you.

  python tools/demo_lab.py --hub http://localhost:8000 --admin admin --password 'admin-pass'

If the hub runs in Docker and must reach the DD mock on this machine, pass
--dd-url-for-hub http://host.docker.internal:5003 (Docker Desktop) or your
host's LAN IP. The hub needs the DD API key in its environment:
TARGETHUB_DD_API_KEY=demo-dd-key (see docker-compose.yml / .env).
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SIM_DIR = ROOT / "tools" / "simulators"
AGENT = ROOT / "backend" / "app" / "web" / "agent" / "targethub_agent.py"
IS_WINDOWS = sys.platform.startswith("win")
DD_KEY = "demo-dd-key"
MAC = "AA:BB:CC:DD:EE:01"


class Hub:
    def __init__(self, base: str):
        self.base = base.rstrip("/")
        self.token: str | None = None

    def call(self, method: str, path: str, body=None, form=None, ok=(200, 201, 204)):
        headers = {"Accept": "application/json"}
        data = None
        if form is not None:
            data = urllib.parse.urlencode(form).encode()
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        elif body is not None:
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        request = urllib.request.Request(f"{self.base}/api/v1{path}", data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                raw = response.read().decode()
                return response.status, (json.loads(raw) if raw else None)
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode(errors="replace")
            if exc.code in ok:
                return exc.code, None
            try:
                detail = json.loads(raw).get("detail")
            except (ValueError, AttributeError):
                detail = raw
            raise SystemExit(f"{method} {path} failed ({exc.code}): {detail}") from None


def wait_for(url: str, seconds: float = 30) -> None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=3):
                return
        except urllib.error.HTTPError:
            return
        except (urllib.error.URLError, OSError):
            time.sleep(0.5)
    raise SystemExit(f"timed out waiting for {url}")


def main() -> int:
    parser = argparse.ArgumentParser(description="TargetHub simulated demo lab")
    parser.add_argument("--hub", default="http://localhost:8000")
    parser.add_argument("--admin", default="admin")
    parser.add_argument("--password", required=True)
    parser.add_argument("--bootstrap-token", help="create the admin if the server has no users yet")
    parser.add_argument("--dd-port", type=int, default=5003)
    parser.add_argument("--dd-url-for-hub", help="DD mock URL as seen from the hub (default: http://127.0.0.1:<port>)")
    parser.add_argument("--work-dir", default=os.path.join(tempfile.gettempdir(), "targethub-demo-lab"))
    args = parser.parse_args()

    work = Path(args.work_dir)
    work.mkdir(parents=True, exist_ok=True)
    processes: list[subprocess.Popen] = []

    def spawn(name: str, command: list[str]) -> subprocess.Popen:
        log = open(work / f"{name}.log", "ab")
        proc = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT, cwd=ROOT)
        processes.append(proc)
        return proc

    def stop_all(*_args):
        for proc in reversed(processes):
            if proc.poll() is None:
                proc.terminate()
        for proc in processes:
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()

    signal.signal(signal.SIGINT, lambda *_: (stop_all(), sys.exit(0)))
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, lambda *_: (stop_all(), sys.exit(0)))

    hub = Hub(args.hub)
    wait_for(f"{hub.base}/health/live")
    _, setup = hub.call("GET", "/auth/setup-status")
    if setup and setup.get("setup_required"):
        if not args.bootstrap_token:
            raise SystemExit("Server has no users yet: pass --bootstrap-token (ADMIN_BOOTSTRAP_TOKEN) to create the admin")
        hub.call("POST", "/auth/bootstrap", {"username": args.admin, "password": args.password, "bootstrap_token": args.bootstrap_token})
    _, tokens = hub.call("POST", "/auth/token", form={"username": args.admin, "password": args.password})
    hub.token = tokens["access_token"]

    # 1. DD mock
    spawn("dd-mock", [sys.executable, str(SIM_DIR / "dd_mock_server.py"), "--port", str(args.dd_port),
                      "--hub-mac", MAC, "--api-key", DD_KEY, "--confirm-delay", "0.7"])
    dd_local = f"http://127.0.0.1:{args.dd_port}"
    wait_for(f"{dd_local}/_mock/state")
    dd_for_hub = args.dd_url_for_hub or dd_local

    # 2. Virtual board following DD node 1 / endpoint 1
    if IS_WINDOWS:
        serial_resource = {"resource_key": "sim://demo-board-01", "resource_type": "serial",
                           "display_name": "Simulated board console", "metadata": {"simulated": True}}
    else:
        link = str(work / "ttyVBOARD0")
        spawn("virtual-board", [sys.executable, str(SIM_DIR / "virtual_board.py"), "--link", link,
                                "--dd-url", dd_local, "--hub-mac", MAC, "--node", "1", "--endpoint", "1",
                                "--api-key", DD_KEY])
        deadline = time.monotonic() + 10
        while not os.path.exists(link) and time.monotonic() < deadline:
            time.sleep(0.1)
        serial_resource = {"resource_key": link, "resource_type": "serial", "display_name": "Virtual board console",
                           "metadata": {"path": link, "baudrate": 115200}}

    # 3. Agent
    agent_name = f"demo-agent-{os.getpid()}"
    _, enrollment = hub.call("POST", "/agents/enrollments", {"agent_name": agent_name})
    config = {
        "targethub_url": hub.base,
        "allow_insecure_http": hub.base.startswith("http://"),
        "enrollment_token": enrollment["token"],
        "heartbeat_interval": 5,
        "operation_poll_wait_seconds": 10,
        "resources": [serial_resource],
    }
    config_path = work / "agent.json"
    config_path.write_text(json.dumps(config, indent=2))
    spawn("agent", [sys.executable, str(AGENT), "--config", str(config_path)] + (["--insecure"] if config["allow_insecure_http"] else []))

    agent = None
    deadline = time.monotonic() + 40
    while time.monotonic() < deadline:
        _, agents = hub.call("GET", "/agents")
        agent = next((item for item in agents if item["name"] == agent_name and item["status"] == "online"
                      and any(r["resource_key"] == serial_resource["resource_key"] for r in item["resources"])), None)
        if agent:
            break
        time.sleep(1)
    if agent is None:
        stop_all()
        raise SystemExit(f"agent did not come online; see {work / 'agent.log'}")
    resource_id = next(r["id"] for r in agent["resources"] if r["resource_key"] == serial_resource["resource_key"])

    # 4. Targets
    def dd_power(endpoint: int) -> dict:
        return {"name": "Power (DD)", "capability_type": "power", "provider_config": {
            "driver": "dd", "base_url": dd_for_hub, "hub_mac": MAC, "node_id": 1, "endpoint": endpoint,
            "api_key_env": "TARGETHUB_DD_API_KEY", "cycle_delay_seconds": 2, "confirm_timeout_seconds": 5}}

    _, existing = hub.call("GET", "/targets")
    for target in existing:
        if target["name"] in {"DEMO-BOARD-01", "DEMO-POWER-02"}:
            hub.call("DELETE", f"/targets/{target['id']}")
    hub.call("POST", "/targets", {
        "name": "DEMO-BOARD-01", "vendor": "TargetHub", "board_model": "Virtual Board", "lab_name": "Demo Lab",
        "location": "Simulator", "tags": ["demo", "virtual"],
        "description": "Serial console from the Agent; power from the (mock) DD system. Power-cycle it and watch it reboot.",
        "capabilities": [
            {"name": "Console", "capability_type": "serial", "agent_id": agent["id"], "resource_id": resource_id},
            dd_power(1),
        ],
    })
    hub.call("POST", "/targets", {
        "name": "DEMO-POWER-02", "vendor": "TargetHub", "board_model": "Relay only", "lab_name": "Demo Lab",
        "tags": ["demo", "power-only"], "description": "Server-hosted DD power; no Agent involved.",
        "capabilities": [dd_power(2)],
    })

    print(f"""
Demo lab is running (logs in {work}).

  Open {hub.base}/app and log in as {args.admin}.
  * Targets: DEMO-BOARD-01 and DEMO-POWER-02 (tag "demo").
  * Reserve DEMO-BOARD-01, open its Console session and its Power session.
  * Power ON: the virtual board boots on the console. Power cycle/reset: it reboots.
  * Type 'help' in the console.
  * DD mock controls: {dd_local}/_mock/state, POST {dd_local}/_mock/emergency?active=1

  The hub must have TARGETHUB_DD_API_KEY={DD_KEY} in its environment for DD power.

Press Ctrl+C to stop the simulators and the agent.
""", flush=True)
    try:
        while all(proc.poll() is None for proc in processes):
            time.sleep(1)
        failed = [proc.args[1] for proc in processes if proc.poll() is not None]
        print(f"a component exited: {failed}; see logs in {work}")
    finally:
        stop_all()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
