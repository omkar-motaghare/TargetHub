#!/usr/bin/env python3
"""Small dependency-free TargetHub Agent runtime for Linux hosts."""

from __future__ import annotations

import argparse
import json
import os
import select
import socket
import sys
import termios
import time
import urllib.error
import urllib.request
from glob import glob
from pathlib import Path
from tty import setraw

DEFAULT_INTERVAL = 15
DEFAULT_REQUEST_TIMEOUT = 15
DEFAULT_OPERATION_POLL_WAIT_SECONDS = 5
MAX_RETRY_DELAY = 120
MAX_SERIAL_READ_SIZE = 65536

_BAUD_TO_TERM = {
    9600: termios.B9600,
    19200: termios.B19200,
    38400: termios.B38400,
    57600: termios.B57600,
    115200: termios.B115200,
    230400: termios.B230400,
}


def load_config(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def save_config(path: Path, config: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(config, indent=2), encoding="utf-8")
    os.chmod(temporary, 0o600)
    temporary.replace(path)


def api_request(
    url: str,
    payload: dict,
    headers: dict | None = None,
    timeout: int = DEFAULT_REQUEST_TIMEOUT,
) -> dict:
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json", **(headers or {})},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8")
            return json.loads(body) if body else {}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"TargetHub request failed ({exc.code}): {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Unable to reach TargetHub: {exc.reason}") from exc


def ensure_linux() -> None:
    if sys.platform != "linux":
        raise RuntimeError("TargetHub Agent currently supports Linux hosts only")


def discover_resources(config: dict) -> list[dict]:
    resources: list[dict] = []
    hostname = socket.gethostname()

    # Prefer stable /dev/serial/by-id paths when available. They are often
    # symlinks to the same devices exposed as /dev/ttyUSB* or /dev/ttyACM*.
    # Reporting both would make one physical serial device appear twice in the UI.
    serial_candidates = sorted(
        set(glob("/dev/serial/by-id/*") + glob("/dev/ttyUSB*") + glob("/dev/ttyACM*"))
    )
    seen_serial_devices: set[str] = set()
    stable_serials = [path for path in serial_candidates if path.startswith("/dev/serial/by-id/")]
    fallback_serials = [path for path in serial_candidates if not path.startswith("/dev/serial/by-id/")]

    for path in stable_serials + fallback_serials:
        try:
            physical_path = os.path.realpath(path)
        except OSError:
            physical_path = path
        if physical_path in seen_serial_devices:
            continue
        seen_serial_devices.add(physical_path)
        resources.append(
            {
                "resource_key": path,
                "resource_type": "serial",
                "display_name": Path(path).name,
                "metadata": {
                    "path": path,
                    "physical_path": physical_path,
                    "hostname": hostname,
                },
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


def _redact(value: str, secrets: list[str]) -> str:
    output = value
    for secret in secrets:
        if secret:
            output = output.replace(secret, "******")
    return output


def _next_retry_delay(previous_delay: int) -> int:
    if previous_delay <= 0:
        return 5
    return min(previous_delay * 2, MAX_RETRY_DELAY)


def _is_fatal_enrollment_error(error: Exception) -> bool:
    message = str(error).lower()
    markers = (
        "invalid enrollment token",
        "already been used",
        "expired",
    )
    return any(marker in message for marker in markers)


def enroll(config: dict, config_path: Path, request_timeout: int = DEFAULT_REQUEST_TIMEOUT) -> None:
    targethub_url = config["targethub_url"].rstrip("/")
    token = config.get("enrollment_token")
    if not token:
        return

    result = api_request(
        f"{targethub_url}/api/v1/agents/enroll",
        {
            "token": token,
            "hostname": socket.gethostname(),
        },
        timeout=request_timeout,
    )
    config["agent_id"] = result["agent"]["id"]
    config["credential"] = result["credential"]
    config.pop("enrollment_token", None)
    save_config(config_path, config)
    print(f"Enrolled Agent {config['agent_id']}")


def heartbeat(config: dict, request_timeout: int = DEFAULT_REQUEST_TIMEOUT) -> None:
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
        timeout=request_timeout,
    )


def poll_operation(
    config: dict,
    *,
    wait_seconds: int,
    request_timeout: int = DEFAULT_REQUEST_TIMEOUT,
) -> dict:
    targethub_url = config["targethub_url"].rstrip("/")
    agent_id = config["agent_id"]
    credential = config["credential"]
    lease_seconds = max(10, wait_seconds * 3)
    return api_request(
        f"{targethub_url}/api/v1/agents/{agent_id}/operations/poll",
        {
            "wait_seconds": wait_seconds,
            "lease_seconds": lease_seconds,
        },
        {"Authorization": f"Bearer {credential}"},
        timeout=request_timeout,
    )


def complete_operation(
    config: dict,
    *,
    operation_id: str,
    success: bool,
    message: str,
    data: dict | None = None,
    request_timeout: int = DEFAULT_REQUEST_TIMEOUT,
) -> dict:
    targethub_url = config["targethub_url"].rstrip("/")
    agent_id = config["agent_id"]
    credential = config["credential"]
    return api_request(
        f"{targethub_url}/api/v1/agents/{agent_id}/operations/{operation_id}/complete",
        {
            "success": success,
            "message": message,
            "data": data or {},
        },
        {"Authorization": f"Bearer {credential}"},
        timeout=request_timeout,
    )


class SerialRuntime:
    def __init__(self) -> None:
        self._open_fds: dict[tuple[str, str], int] = {}
        self._sim_open: set[tuple[str, str]] = set()
        self._sim_buffers: dict[tuple[str, str], str] = {}

    @staticmethod
    def _resource_key(operation_payload: dict) -> tuple[str, str]:
        return (
            str(operation_payload.get("session_id", "")),
            str(operation_payload.get("resource_id", "")),
        )

    @staticmethod
    def _is_simulated(operation_payload: dict) -> bool:
        resource_key = str(operation_payload.get("resource_key", ""))
        metadata = operation_payload.get("resource_metadata") or {}
        return bool(metadata.get("simulated")) or resource_key.startswith("sim://")

    @staticmethod
    def _resolve_path(operation_payload: dict) -> str:
        metadata = operation_payload.get("resource_metadata") or {}
        path = metadata.get("path")
        if isinstance(path, str) and path:
            return path
        return str(operation_payload.get("resource_key", ""))

    @staticmethod
    def _configure_fd(fd: int, metadata: dict) -> None:
        baudrate = int(metadata.get("baudrate", 115200))
        speed = _BAUD_TO_TERM.get(baudrate, termios.B115200)
        attributes = termios.tcgetattr(fd)
        attributes[4] = speed
        attributes[5] = speed
        termios.tcsetattr(fd, termios.TCSANOW, attributes)
        setraw(fd)

    @staticmethod
    def _as_text(value: object) -> str:
        if isinstance(value, str):
            return value
        return str(value)

    @staticmethod
    def _read_size(params: dict) -> int:
        size = int(params.get("size", 4096))
        return max(1, min(size, MAX_SERIAL_READ_SIZE))

    def execute(self, operation_payload: dict) -> dict:
        operation = str(operation_payload.get("operation", "")).strip().lower()
        params = operation_payload.get("params") or {}
        key = self._resource_key(operation_payload)
        if not key[0] or not key[1]:
            return {"success": False, "message": "Operation is missing session/resource binding"}

        if self._is_simulated(operation_payload):
            return self._execute_simulated(operation, key, params)
        return self._execute_real(operation_payload, operation, key, params)

    def _execute_simulated(self, operation: str, key: tuple[str, str], params: dict) -> dict:
        if operation == "open":
            if key not in self._sim_open:
                self._sim_open.add(key)
                self._sim_buffers[key] = "[simulated] serial console ready\r\n"
            return {"success": True, "message": "Serial connection opened", "data": {"mode": "simulated"}}

        if operation == "close":
            self._sim_open.discard(key)
            self._sim_buffers.pop(key, None)
            return {"success": True, "message": "Serial connection closed", "data": {"mode": "simulated"}}

        if key not in self._sim_open:
            return {"success": False, "message": "Serial connection is not open"}

        if operation == "write":
            text = self._as_text(params.get("text", ""))
            self._sim_buffers[key] = self._sim_buffers.get(key, "") + f"{text}\r\n"
            return {
                "success": True,
                "message": "Serial data written",
                "data": {"bytes_written": len(text.encode("utf-8")), "mode": "simulated"},
            }

        if operation == "read":
            content = self._sim_buffers.get(key, "")
            self._sim_buffers[key] = ""
            data = content.encode("utf-8")
            return {
                "success": True,
                "message": "Serial data read",
                "data": {
                    "bytes_read": len(data),
                    "data_text": content,
                    "data_hex": data.hex(),
                    "mode": "simulated",
                },
            }

        return {"success": False, "message": f"Unsupported serial operation '{operation}'"}

    def _execute_real(
        self,
        operation_payload: dict,
        operation: str,
        key: tuple[str, str],
        params: dict,
    ) -> dict:
        path = self._resolve_path(operation_payload)
        metadata = operation_payload.get("resource_metadata") or {}

        if operation == "open":
            if key in self._open_fds:
                return {"success": True, "message": "Serial connection already open", "data": {"path": path}}
            if not path.startswith("/dev/"):
                return {"success": False, "message": f"Serial path '{path}' is not allowed"}
            try:
                fd = os.open(path, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
                self._configure_fd(fd, metadata)
                self._open_fds[key] = fd
                return {"success": True, "message": "Serial connection opened", "data": {"path": path}}
            except OSError as exc:
                return {"success": False, "message": f"Failed to open serial connection: {exc}"}

        if operation == "close":
            fd = self._open_fds.pop(key, None)
            if fd is None:
                return {"success": True, "message": "Serial connection already closed", "data": {"path": path}}
            try:
                os.close(fd)
            except OSError:
                pass
            return {"success": True, "message": "Serial connection closed", "data": {"path": path}}

        fd = self._open_fds.get(key)
        if fd is None:
            return {"success": False, "message": "Serial connection is not open"}

        if operation == "write":
            text = self._as_text(params.get("text", ""))
            payload = text.encode("utf-8")
            try:
                written = os.write(fd, payload)
                return {
                    "success": True,
                    "message": "Serial data written",
                    "data": {"bytes_written": written, "path": path},
                }
            except OSError as exc:
                return {"success": False, "message": f"Failed to write serial data: {exc}"}

        if operation == "read":
            size = self._read_size(params)
            timeout = float(metadata.get("timeout", 0.2))
            try:
                readable, _, _ = select.select([fd], [], [], max(0.0, timeout))
                data = os.read(fd, size) if readable else b""
                return {
                    "success": True,
                    "message": "Serial data read",
                    "data": {
                        "bytes_read": len(data),
                        "data_text": data.decode("utf-8", errors="replace"),
                        "data_hex": data.hex(),
                        "path": path,
                    },
                }
            except OSError as exc:
                return {"success": False, "message": f"Failed to read serial data: {exc}"}

        return {"success": False, "message": f"Unsupported serial operation '{operation}'"}


def main() -> int:
    ensure_linux()
    parser = argparse.ArgumentParser(description="TargetHub Agent")
    parser.add_argument("--config", default="/etc/targethub-agent/config.json")
    args = parser.parse_args()
    config_path = Path(args.config)
    config = load_config(config_path)
    interval = max(5, int(config.get("heartbeat_interval", DEFAULT_INTERVAL)))
    request_timeout = max(5, int(config.get("request_timeout", DEFAULT_REQUEST_TIMEOUT)))
    operation_poll_wait_seconds = max(
        1,
        min(
            int(config.get("operation_poll_wait_seconds", DEFAULT_OPERATION_POLL_WAIT_SECONDS)),
            interval,
        ),
    )

    if config.get("enrollment_token"):
        enrollment_delay = 0
        while config.get("enrollment_token"):
            try:
                enroll(config, config_path, request_timeout=request_timeout)
            except Exception as exc:
                if _is_fatal_enrollment_error(exc):
                    print("enrollment failed permanently; create a new enrollment token", file=sys.stderr)
                    return 1
                enrollment_delay = _next_retry_delay(enrollment_delay)
                print(
                    _redact(
                        f"enrollment error: {exc}; retrying in {enrollment_delay}s",
                        [str(config.get("enrollment_token", ""))],
                    ),
                    file=sys.stderr,
                )
                time.sleep(enrollment_delay)
            else:
                enrollment_delay = 0

    if not config.get("agent_id") or not config.get("credential"):
        raise RuntimeError("Agent is not enrolled. Provide an enrollment token in the configuration.")

    print(f"TargetHub Agent running as {config['agent_id']}")
    serial_runtime = SerialRuntime()
    failure_delay = 0
    next_heartbeat_due = 0.0
    while True:
        try:
            if time.monotonic() >= next_heartbeat_due:
                heartbeat(config, request_timeout=request_timeout)
                next_heartbeat_due = time.monotonic() + interval

            poll_timeout = max(request_timeout, operation_poll_wait_seconds + 5)
            poll_result = poll_operation(
                config,
                wait_seconds=operation_poll_wait_seconds,
                request_timeout=poll_timeout,
            )
            operation = poll_result.get("operation")
            if operation:
                execution = serial_runtime.execute(operation)
                complete_operation(
                    config,
                    operation_id=str(operation["id"]),
                    success=bool(execution.get("success")),
                    message=str(execution.get("message", "")),
                    data=execution.get("data") if isinstance(execution.get("data"), dict) else {},
                    request_timeout=request_timeout,
                )
            failure_delay = 0
        except Exception as exc:  # keep the service alive through transient failures
            failure_delay = _next_retry_delay(failure_delay)
            secrets = [
                str(config.get("credential", "")),
                str(config.get("enrollment_token", "")),
            ]
            print(
                _redact(
                    f"heartbeat/operation error: {exc}; retrying in {failure_delay}s",
                    secrets,
                ),
                file=sys.stderr,
            )
            time.sleep(failure_delay)


if __name__ == "__main__":
    raise SystemExit(main())
