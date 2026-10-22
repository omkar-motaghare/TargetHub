#!/usr/bin/env python3
"""Small dependency-free TargetHub Agent runtime for Linux hosts."""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import random
import select
import signal
import socket
import ssl
import subprocess
import sys
import tempfile
import termios
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from glob import glob
from pathlib import Path
from tty import setraw

log = logging.getLogger("targethub-agent")

DEFAULT_INTERVAL = 15
DEFAULT_REQUEST_TIMEOUT = 15
DEFAULT_OPERATION_POLL_WAIT_SECONDS = 5
MAX_RETRY_DELAY = 120
MAX_SERIAL_READ_SIZE = 65536
MAX_USB_DEVICES = 32
MAX_ARTIFACT_BYTES = 256 * 1024 * 1024
DEFAULT_DEPLOY_TIMEOUT = 300
DEFAULT_GPIO_BASE = "/sys/class/gpio"

_ssl_context: ssl.SSLContext | None = None
_stop = threading.Event()

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


def configure_tls(config: dict) -> None:
    """Use a custom CA bundle for the hub when configured; default verification stays on."""
    global _ssl_context
    ca_bundle = config.get("ca_bundle")
    _ssl_context = ssl.create_default_context(cafile=ca_bundle) if ca_bundle else None


def validate_hub_url(config: dict, allow_insecure: bool) -> None:
    url = str(config.get("targethub_url", ""))
    if url.startswith("https://"):
        return
    if url.startswith("http://") and (allow_insecure or config.get("allow_insecure_http")):
        log.warning("using plain http to reach TargetHub; credentials are not protected")
        return
    raise RuntimeError("targethub_url must be https:// (use allow_insecure_http or --insecure for lab testing)")


def sd_notify(message: str) -> None:
    address = os.environ.get("NOTIFY_SOCKET")
    if not address:
        return
    if address.startswith("@"):
        address = "\0" + address[1:]
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as sock:
            sock.connect(address)
            sock.sendall(message.encode("utf-8"))
    except OSError as exc:
        log.debug("sd_notify failed: %s", exc)


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
        with urllib.request.urlopen(request, timeout=timeout, context=_ssl_context) as response:
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


def _read_sysfs_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def discover_usb_devices(hostname: str) -> list[dict]:
    devices: list[dict] = []
    for path in sorted(glob("/sys/bus/usb/devices/*")):
        entry = Path(path)
        vendor_id = _read_sysfs_text(entry / "idVendor")
        if not vendor_id or entry.name.startswith("usb"):
            continue
        product = _read_sysfs_text(entry / "product") or entry.name
        devices.append(
            {
                "resource_key": f"usb:{entry.name}",
                "resource_type": "usb_device",
                "display_name": product,
                "metadata": {
                    "vendor_id": vendor_id,
                    "product_id": _read_sysfs_text(entry / "idProduct"),
                    "product": product,
                    "hostname": hostname,
                },
                "available": True,
            }
        )
        if len(devices) >= MAX_USB_DEVICES:
            break
    return devices


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

    for path in sorted(glob("/dev/gpiochip*")):
        resources.append(
            {
                "resource_key": f"gpio:{Path(path).name}",
                "resource_type": "gpio_chip",
                "display_name": Path(path).name,
                "metadata": {"path": path, "hostname": hostname},
                "available": True,
            }
        )

    resources.extend(discover_usb_devices(hostname))

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

    # The token is single use: prove the credential can be persisted before spending it.
    save_config(config_path, config)
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
    log.info("Enrolled Agent %s", config["agent_id"])


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

    def close_all(self) -> None:
        for fd in self._open_fds.values():
            try:
                os.close(fd)
            except OSError as exc:
                log.debug("serial close failed: %s", exc)
        self._open_fds.clear()

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
            except OSError as exc:
                log.debug("serial close failed: %s", exc)
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


class SysfsGpio:
    """GPIO output lines through the (deprecated but universal) sysfs interface."""

    def __init__(self, base: str) -> None:
        self.base = Path(base)

    def _line_dir(self, line: int) -> Path:
        return self.base / f"gpio{line}"

    def write(self, line: int, level: int) -> None:
        line_dir = self._line_dir(line)
        if not line_dir.exists():
            (self.base / "export").write_text(str(line), encoding="utf-8")
        direction_path = line_dir / "direction"
        if _read_sysfs_text(direction_path) != "out":
            # "high"/"low" set the direction and initial level together, avoiding a glitch.
            direction_path.write_text("high" if level else "low", encoding="utf-8")
        (line_dir / "value").write_text("1" if level else "0", encoding="utf-8")

    def read(self, line: int) -> int:
        return int(_read_sysfs_text(self._line_dir(line) / "value") or 0)


class GpiodCli:
    """GPIO output lines held by a long-running libgpiod `gpioset` process per line."""

    def __init__(self, chip: str, version: int) -> None:
        self.chip = chip
        self.version = version
        self._procs: dict[int, subprocess.Popen] = {}
        self._levels: dict[int, int] = {}

    def _command(self, line: int, level: int) -> list[str]:
        if self.version == 1:
            return ["gpioset", "--mode=signal", self.chip, f"{line}={level}"]
        return ["gpioset", "--chip", self.chip, f"{line}={level}"]

    def write(self, line: int, level: int) -> None:
        self._release(line)
        self._procs[line] = subprocess.Popen(
            self._command(line, level),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        self._levels[line] = level

    def read(self, line: int) -> int:
        return self._levels.get(line, 0)

    def _release(self, line: int) -> None:
        proc = self._procs.pop(line, None)
        if proc is not None:
            proc.terminate()
            proc.wait(timeout=5)


class PowerRuntime:
    """Relay/reset-line control for resources defined in the local Agent config."""

    def __init__(self) -> None:
        self._gpiod: dict[tuple[str, int], GpiodCli] = {}

    def _backend(self, metadata: dict):
        backend = str(metadata.get("backend", "sysfs"))
        if backend == "sysfs":
            return SysfsGpio(str(metadata.get("gpio_base", DEFAULT_GPIO_BASE)))
        if backend == "gpiod":
            chip = str(metadata.get("chip", "gpiochip0"))
            version = int(metadata.get("gpiod_version", 2))
            return self._gpiod.setdefault((chip, version), GpiodCli(chip, version))
        raise ValueError(f"Unsupported GPIO backend '{backend}'")

    @staticmethod
    def _pulse_seconds(metadata: dict) -> float:
        return max(0.05, min(float(metadata.get("pulse_seconds", 0.5)), 10.0))

    def execute(self, operation: str, metadata: dict) -> dict:
        try:
            gpio = self._backend(metadata)
            line = int(metadata["line"])
        except (KeyError, TypeError, ValueError) as exc:
            return {"success": False, "message": f"Invalid power resource configuration: {exc}"}
        active_low = bool(metadata.get("active_low", False))

        def level_for(on: bool) -> int:
            return 0 if on == active_low else 1

        try:
            if operation == "status":
                is_on = (gpio.read(line) == 1) != active_low
                return {"success": True, "message": "Power status", "data": {"state": "on" if is_on else "off"}}
            if operation in {"on", "off"}:
                gpio.write(line, level_for(operation == "on"))
                return {"success": True, "message": f"Power {operation}", "data": {"state": operation}}
            if operation in {"reset", "cycle"}:
                pulse = self._pulse_seconds(metadata)
                is_reset_line = metadata.get("kind") == "reset_line"
                gpio.write(line, level_for(is_reset_line))
                time.sleep(pulse)
                gpio.write(line, level_for(not is_reset_line))
                final_state = "off" if is_reset_line else "on"
                return {"success": True, "message": f"Power {operation} complete", "data": {"state": final_state}}
        except (OSError, subprocess.SubprocessError) as exc:
            return {"success": False, "message": f"GPIO operation failed: {exc}"}
        return {"success": False, "message": f"Unsupported power operation '{operation}'"}


class DeployRuntime:
    """Download a checksummed artifact and hand it to an operator-configured command."""

    def __init__(self) -> None:
        self._last: dict = {}

    @staticmethod
    def _download(url: str, destination: Path, allow_http: bool) -> str:
        scheme = urllib.parse.urlparse(url).scheme
        if scheme != "https" and not (scheme == "http" and allow_http):
            raise ValueError("Artifact URL must use https")
        digest = hashlib.sha256()
        size = 0
        with urllib.request.urlopen(url, timeout=DEFAULT_REQUEST_TIMEOUT, context=_ssl_context) as response:
            with destination.open("wb") as handle:
                while True:
                    chunk = response.read(65536)
                    if not chunk:
                        break
                    size += len(chunk)
                    if size > MAX_ARTIFACT_BYTES:
                        raise ValueError("Artifact exceeds the maximum allowed size")
                    digest.update(chunk)
                    handle.write(chunk)
        return digest.hexdigest()

    def execute(self, operation: str, params: dict, metadata: dict) -> dict:
        if operation == "status":
            return {"success": True, "message": "Last deployment", "data": dict(self._last) or {"status": "none"}}
        if operation != "deploy":
            return {"success": False, "message": f"Unsupported deploy operation '{operation}'"}

        command = metadata.get("command")
        if not isinstance(command, list) or not command or not all(isinstance(part, str) for part in command):
            return {"success": False, "message": "Deploy resource has no command configured on this Agent"}
        url = str(params.get("url", ""))
        expected = str(params.get("sha256", "")).lower()
        timeout = max(5, min(int(metadata.get("timeout", DEFAULT_DEPLOY_TIMEOUT)), 3600))

        with tempfile.TemporaryDirectory(prefix="targethub-deploy-") as workdir:
            artifact = Path(workdir) / "artifact.bin"
            try:
                actual = self._download(url, artifact, bool(metadata.get("allow_http")))
            except (OSError, ValueError, urllib.error.URLError) as exc:
                return {"success": False, "message": f"Artifact download failed: {exc}"}
            if actual != expected:
                return {"success": False, "message": "Artifact sha256 mismatch; refusing to deploy"}
            args = [part.replace("{artifact}", str(artifact)) for part in command]
            try:
                completed = subprocess.run(
                    args, cwd=workdir, capture_output=True, text=True, timeout=timeout, check=False
                )
            except (OSError, subprocess.SubprocessError) as exc:
                return {"success": False, "message": f"Deploy command failed to run: {exc}"}

        output = (completed.stdout + completed.stderr)[-2000:]
        self._last = {"status": "ok" if completed.returncode == 0 else "failed", "sha256": actual}
        return {
            "success": completed.returncode == 0,
            "message": "Deployment complete" if completed.returncode == 0 else f"Deploy command exited {completed.returncode}",
            "data": {**self._last, "returncode": completed.returncode, "output": output},
        }


class OperationRouter:
    """Dispatch hub operations to the runtime for their resource type."""

    def __init__(self, config: dict) -> None:
        self.config = config
        self.serial = SerialRuntime()
        self.power = PowerRuntime()
        self.deploy = DeployRuntime()

    def _local_metadata(self, resource_key: str) -> dict | None:
        # Power/deploy settings come from the local config only; the hub's copy is not trusted.
        for item in self.config.get("resources", []):
            if item.get("resource_key") == resource_key:
                return item.get("metadata") or {}
        return None

    def execute(self, payload: dict) -> dict:
        resource_type = str(payload.get("resource_type", ""))
        operation = str(payload.get("operation", "")).strip().lower()
        params = payload.get("params") or {}
        if resource_type == "serial":
            return self.serial.execute(payload)
        if resource_type in {"power", "reset", "deploy"}:
            metadata = self._local_metadata(str(payload.get("resource_key", "")))
            if metadata is None:
                return {"success": False, "message": "Resource is not configured on this Agent"}
            if resource_type == "deploy":
                return self.deploy.execute(operation, params, metadata)
            return self.power.execute(operation, metadata)
        return {"success": False, "message": f"Unsupported resource type '{resource_type}'"}


def run_operation(config: dict, router: OperationRouter, operation: dict, request_timeout: int) -> None:
    try:
        execution = router.execute(operation)
        complete_operation(
            config,
            operation_id=str(operation["id"]),
            success=bool(execution.get("success")),
            message=str(execution.get("message", "")),
            data=execution.get("data") if isinstance(execution.get("data"), dict) else {},
            request_timeout=request_timeout,
        )
    except Exception as exc:  # the hub times the operation out if completion is never reported
        log.warning(_redact(f"operation {operation.get('id')} failed: {exc}", [str(config.get("credential", ""))]))


def _jittered(delay: int) -> float:
    return delay * random.uniform(0.5, 1.0)


def _handle_stop(_signum: int, _frame: object) -> None:
    _stop.set()


def main() -> int:
    ensure_linux()
    parser = argparse.ArgumentParser(description="TargetHub Agent")
    parser.add_argument("--config", default="/etc/targethub-agent/config.json")
    parser.add_argument("--insecure", action="store_true", help="allow a plain http:// TargetHub URL")
    args = parser.parse_args()
    # journald captures stderr and adds timestamps.
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s", stream=sys.stderr)
    signal.signal(signal.SIGTERM, _handle_stop)
    signal.signal(signal.SIGINT, _handle_stop)

    config_path = Path(args.config)
    config = load_config(config_path)
    validate_hub_url(config, args.insecure)
    configure_tls(config)
    interval = max(5, int(config.get("heartbeat_interval", DEFAULT_INTERVAL)))
    request_timeout = max(5, int(config.get("request_timeout", DEFAULT_REQUEST_TIMEOUT)))
    operation_poll_wait_seconds = max(
        1,
        min(
            int(config.get("operation_poll_wait_seconds", DEFAULT_OPERATION_POLL_WAIT_SECONDS)),
            interval,
        ),
    )

    enrollment_delay = 0
    while config.get("enrollment_token") and not _stop.is_set():
        try:
            enroll(config, config_path, request_timeout=request_timeout)
        except Exception as exc:
            if _is_fatal_enrollment_error(exc):
                log.error("enrollment failed permanently; create a new enrollment token")
                return 1
            enrollment_delay = _next_retry_delay(enrollment_delay)
            log.warning(
                _redact(
                    f"enrollment error: {exc}; retrying in {enrollment_delay}s",
                    [str(config.get("enrollment_token", ""))],
                )
            )
            _stop.wait(_jittered(enrollment_delay))

    if _stop.is_set():
        return 0
    if not config.get("agent_id") or not config.get("credential"):
        raise RuntimeError("Agent is not enrolled. Provide an enrollment token in the configuration.")

    log.info("TargetHub Agent running as %s", config["agent_id"])
    sd_notify("READY=1")
    router = OperationRouter(config)
    failure_delay = 0
    next_heartbeat_due = 0.0
    worker: threading.Thread | None = None
    while not _stop.is_set():
        sd_notify("WATCHDOG=1")
        try:
            if time.monotonic() >= next_heartbeat_due:
                heartbeat(config, request_timeout=request_timeout)
                next_heartbeat_due = time.monotonic() + interval

            if worker is not None and worker.is_alive():
                # An operation is running: keep heartbeating but do not claim another.
                _stop.wait(1)
                continue

            poll_timeout = max(request_timeout, operation_poll_wait_seconds + 5)
            poll_result = poll_operation(
                config,
                wait_seconds=operation_poll_wait_seconds,
                request_timeout=poll_timeout,
            )
            operation = poll_result.get("operation")
            if operation:
                worker = threading.Thread(
                    target=run_operation,
                    args=(config, router, operation, request_timeout),
                    daemon=True,
                )
                worker.start()
            failure_delay = 0
        except Exception as exc:  # keep the service alive through transient failures
            failure_delay = _next_retry_delay(failure_delay)
            secrets = [
                str(config.get("credential", "")),
                str(config.get("enrollment_token", "")),
            ]
            log.warning(
                _redact(
                    f"heartbeat/operation error: {exc}; retrying in {failure_delay}s",
                    secrets,
                )
            )
            _stop.wait(_jittered(failure_delay))

    if worker is not None:
        worker.join(timeout=10)
    sd_notify("STOPPING=1")
    router.serial.close_all()
    log.info("TargetHub Agent stopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
