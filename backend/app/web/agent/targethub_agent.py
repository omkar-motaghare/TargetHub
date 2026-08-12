#!/usr/bin/env python3
"""Small dependency-free TargetHub Agent runtime for supported Linux hosts."""

from __future__ import annotations

import argparse
import json
import os
import platform
import socket
import sys
import time
import urllib.error
import urllib.request
from glob import glob
from pathlib import Path


DEFAULT_INTERVAL = 15


def load_config(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def save_config(path: Path, config: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(config, indent=2), encoding="utf-8")
    os.chmod(temporary, 0o600)
    temporary.replace(path)


def api_request(url: str, payload: dict, headers: dict | None = None) -> dict:
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json", **(headers or {})},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            body = response.read().decode("utf-8")
            return json.loads(body) if body else {}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"TargetHub request failed ({exc.code}): {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Unable to reach TargetHub: {exc.reason}") from exc


def discover_resources(config: dict) -> list[dict]:
    resources: list[dict] = []
    hostname = socket.gethostname()

    for path in sorted(set(glob("/dev/ttyUSB*") + glob("/dev/ttyACM*") + glob("/dev/serial/by-id/*"))):
        resources.append(
            {
                "resource_key": path,
                "resource_type": "serial",
                "display_name": Path(path).name,
                "metadata": {"path": path, "hostname": hostname},
                "available": True,
            }
        )

    for path in sorted(glob("/sys/class/net/*")):
        name = Path(path).name
        if name == "lo":
            continue
        resources.append(
            {
                "resource_key": f"net:{name}",
                "resource_type": "network_interface",
                "display_name": name,
                "metadata": {"interface": name, "hostname": hostname},
                "available": True,
            }
        )

    for item in config.get("resources", []):
        resources.append(
            {
                "resource_key": item["resource_key"],
                "resource_type": item.get("resource_type", "custom"),
                "display_name": item.get("display_name", item["resource_key"]),
                "metadata": item.get("metadata", {}),
                "available": item.get("available", True),
            }
        )

    return resources


def enroll(config: dict, config_path: Path) -> None:
    targethub_url = config["targethub_url"].rstrip("/")
    token = config.get("enrollment_token")
    if not token:
        return

    result = api_request(
        f"{targethub_url}/api/v1/agents/enroll",
        {"token": token, "hostname": socket.gethostname()},
    )
    config["agent_id"] = result["agent"]["id"]
    config["credential"] = result["credential"]
    config.pop("enrollment_token", None)
    save_config(config_path, config)
    print(f"Enrolled Agent {config['agent_id']}")


def heartbeat(config: dict) -> None:
    targethub_url = config["targethub_url"].rstrip("/")
    agent_id = config["agent_id"]
    credential = config["credential"]
    api_request(
        f"{targethub_url}/api/v1/agents/{agent_id}/heartbeat",
        {
            "hostname": socket.gethostname(),
            "resources": discover_resources(config),
        },
        {"Authorization": f"Bearer {credential}"},
    )


def main() -> int:
    if platform.system() != "Linux":
        raise RuntimeError("TargetHub Agent requires a Linux-based machine")

    parser = argparse.ArgumentParser(description="TargetHub Agent")
    parser.add_argument("--config", default="/etc/targethub-agent/config.json")
    args = parser.parse_args()
    config_path = Path(args.config)
    config = load_config(config_path)
    interval = max(5, int(config.get("heartbeat_interval", DEFAULT_INTERVAL)))

    if config.get("enrollment_token"):
        enroll(config, config_path)

    if not config.get("agent_id") or not config.get("credential"):
        raise RuntimeError("Agent is not enrolled. Provide an enrollment token in the configuration.")

    print(f"TargetHub Agent running as {config['agent_id']}")
    while True:
        try:
            heartbeat(config)
        except Exception as exc:
            print(f"heartbeat error: {exc}", file=sys.stderr)
        time.sleep(interval)


if __name__ == "__main__":
    raise SystemExit(main())
