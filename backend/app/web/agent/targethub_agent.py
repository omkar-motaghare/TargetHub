#!/usr/bin/env python3
"""TargetHub Agent: bridges a TargetHub hub to the hardware attached to this host.

Runs on Linux (including Raspberry Pi / Yocto / BusyBox images) and Windows.
The core is standard-library only. ``pyserial`` is used when installed (needed
for serial ports on Windows); on Linux the agent falls back to termios.

Protocol (all HTTPS JSON, authenticated with the Agent credential):
  * heartbeat  - report hostname and discovered resources
  * poll       - long-poll the hub for the next operation
  * complete   - report an operation result
Operations for different resources run concurrently; power and deploy
operations on the same resource are serialized.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import random
import signal
import socket
import ssl
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from glob import glob
from pathlib import Path

AGENT_VERSION = "0.2.0"
IS_WINDOWS = sys.platform.startswith("win")
IS_LINUX = sys.platform.startswith("linux")

if not IS_WINDOWS:  # pragma: no branch - platform specific imports
    import select
    import termios
    from tty import setraw
else:  # pragma: no cover - exercised on Windows only
    select = None  # type: ignore[assignment]
    termios = None  # type: ignore[assignment]
    setraw = None  # type: ignore[assignment]

try:  # optional dependency
    import serial as _pyserial  # type: ignore[import-not-found]
    from serial.tools import list_ports as _list_ports  # type: ignore[import-not-found]
except Exception:  # pragma: no cover - depends on host
    _pyserial = None
    _list_ports = None

log = logging.getLogger("targethub-agent")

DEFAULT_INTERVAL = 15
DEFAULT_REQUEST_TIMEOUT = 15
DEFAULT_OPERATION_POLL_WAIT_SECONDS = 10
DEFAULT_MAX_CONCURRENT_OPERATIONS = 8
DEFAULT_SERIAL_IDLE_TIMEOUT = 900
MAX_RETRY_DELAY = 120
MAX_SERIAL_READ_SIZE = 65536
MAX_SERIAL_READ_WAIT_SECONDS = 5.0
SERIAL_BUFFER_BYTES = 1024 * 1024
SERIAL_COALESCE_SECONDS = 0.03
MAX_USB_DEVICES = 32
MAX_ARTIFACT_BYTES = 256 * 1024 * 1024
DEFAULT_DEPLOY_TIMEOUT = 300
DEFAULT_GPIO_BASE = "/sys/class/gpio"
DEFAULT_CONFIG_PATH = (
    r"C:\ProgramData\TargetHub\agent\config.json" if IS_WINDOWS else "/etc/targethub-agent/config.json"
)

_ssl_context: ssl.SSLContext | None = None
_stop = threading.Event()

SUPPORTED_BAUDRATES = (1200, 2400, 4800, 9600, 19200, 38400, 57600, 115200, 230400, 460800, 921600)


# --------------------------------------------------------------------------- config / http


def load_config(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def save_config(path: Path, config: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(config, indent=2), encoding="utf-8")
    try:
        os.chmod(temporary, 0o600)
    except OSError:  # pragma: no cover - e.g. some Windows filesystems
        pass
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
    if not address or not hasattr(socket, "AF_UNIX"):
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
        headers={
            "Content-Type": "application/json",
            "User-Agent": f"targethub-agent/{AGENT_VERSION}",
            **(headers or {}),
        },
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


def ensure_supported_platform() -> None:
    if not (IS_LINUX or IS_WINDOWS):
        raise RuntimeError("TargetHub Agent supports Linux and Windows hosts")


# Backwards-compatible name used by older installers/tests.
ensure_linux = ensure_supported_platform


# --------------------------------------------------------------------------- discovery


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


def _windows_com_ports() -> list[dict]:  # pragma: no cover - Windows only
    ports: list[dict] = []
    if _list_ports is not None:
        for info in sorted(_list_ports.comports(), key=lambda item: item.device):
            ports.append(
                {
                    "path": info.device,
                    "description": info.description or info.device,
                    "vendor_id": f"{info.vid:04x}" if info.vid is not None else "",
                    "product_id": f"{info.pid:04x}" if info.pid is not None else "",
                    "serial_number": info.serial_number or "",
                }
            )
        return ports
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DEVICEMAP\SERIALCOMM") as key:
            index = 0
            while True:
                try:
                    _name, value, _kind = winreg.EnumValue(key, index)
                except OSError:
                    break
                ports.append({"path": str(value), "description": str(value)})
                index += 1
    except OSError:
        pass
    return sorted(ports, key=lambda item: item["path"])


def _serial_resource(path: str, display: str, metadata: dict) -> dict:
    return {
        "resource_key": path,
        "resource_type": "serial",
        "display_name": display,
        "metadata": metadata,
        "available": True,
    }


def discover_resources(config: dict) -> list[dict]:
    resources: list[dict] = []
    hostname = socket.gethostname()

    if IS_WINDOWS:  # pragma: no cover - Windows only
        for port in _windows_com_ports():
            resources.append(
                _serial_resource(
                    port["path"],
                    f"{port['path']} ({port.get('description') or 'serial'})",
                    {**port, "hostname": hostname},
                )
            )
    else:
        # Prefer stable /dev/serial/by-id paths when available. They are often
        # symlinks to the same devices exposed as /dev/ttyUSB* or /dev/ttyACM*.
        serial_candidates = sorted(
            set(glob("/dev/serial/by-id/*") + glob("/dev/ttyUSB*") + glob("/dev/ttyACM*"))
        )
        seen_serial_devices: set[str] = set()
        stable = [path for path in serial_candidates if path.startswith("/dev/serial/by-id/")]
        fallback = [path for path in serial_candidates if not path.startswith("/dev/serial/by-id/")]
        for path in stable + fallback:
            try:
                physical_path = os.path.realpath(path)
            except OSError:
                physical_path = path
            if physical_path in seen_serial_devices:
                continue
            seen_serial_devices.add(physical_path)
            resources.append(
                _serial_resource(
                    path,
                    Path(path).name,
                    {"path": path, "physical_path": physical_path, "hostname": hostname},
                )
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
                "metadata": _public_metadata(item.get("metadata", {})),
                "available": item.get("available", True),
            }
        )

    return resources


# Local-only keys that must never be reported to the hub (commands, credentials).
_PRIVATE_METADATA_KEYS = {"command", "api_key", "api_key_env", "password", "token"}


def _public_metadata(metadata: dict) -> dict:
    return {key: value for key, value in (metadata or {}).items() if key not in _PRIVATE_METADATA_KEYS}


# --------------------------------------------------------------------------- hub protocol


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


def heartbeat(
    config: dict,
    request_timeout: int = DEFAULT_REQUEST_TIMEOUT,
    resources: list[dict] | None = None,
) -> None:
    targethub_url = config["targethub_url"].rstrip("/")
    agent_id = config["agent_id"]
    credential = config["credential"]
    api_request(
        f"{targethub_url}/api/v1/agents/{agent_id}/heartbeat",
        {
            "hostname": socket.gethostname(),
            "resources": resources if resources is not None else discover_resources(config),
            "agent_version": AGENT_VERSION,
            "platform": sys.platform,
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
    lease_seconds = max(10, min(120, wait_seconds * 3))
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


# --------------------------------------------------------------------------- serial


class _PosixPort:
    """Raw tty access through termios (Linux fallback when pyserial is absent)."""

    def __init__(self, path: str, baudrate: int) -> None:
        self.fd = os.open(path, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
        try:
            speed = getattr(termios, f"B{baudrate}", termios.B115200)
            attributes = termios.tcgetattr(self.fd)
            attributes[4] = speed
            attributes[5] = speed
            termios.tcsetattr(self.fd, termios.TCSANOW, attributes)
            setraw(self.fd)
        except (OSError, termios.error):
            os.close(self.fd)
            raise

    def read(self, size: int, timeout: float) -> bytes:
        readable, _, _ = select.select([self.fd], [], [], max(0.0, timeout))
        if not readable:
            return b""
        try:
            return os.read(self.fd, size)
        except BlockingIOError:
            return b""

    def write(self, data: bytes) -> int:
        total = 0
        deadline = time.monotonic() + 5
        while total < len(data):
            try:
                total += os.write(self.fd, data[total:])
            except BlockingIOError:
                if time.monotonic() > deadline:
                    break
                select.select([], [self.fd], [], 0.1)
        return total

    def close(self) -> None:
        os.close(self.fd)


class _PySerialPort:  # pragma: no cover - exercised where pyserial is installed
    def __init__(self, path: str, baudrate: int) -> None:
        self.port = _pyserial.Serial(path, baudrate=baudrate, timeout=0.2, write_timeout=5)

    def read(self, size: int, timeout: float) -> bytes:
        self.port.timeout = max(0.01, timeout)
        waiting = self.port.in_waiting
        return self.port.read(max(1, min(size, waiting or 1)))

    def write(self, data: bytes) -> int:
        return int(self.port.write(data) or 0)

    def close(self) -> None:
        self.port.close()


def open_serial_port(path: str, baudrate: int):
    if _pyserial is not None:
        return _PySerialPort(path, baudrate)
    if IS_WINDOWS:  # pragma: no cover - Windows only
        raise OSError("pyserial is required for serial ports on Windows (pip install pyserial)")
    return _PosixPort(path, baudrate)


class VirtualBoard:
    """Built-in simulated target for ``sim://`` serial resources.

    Behaves like a small embedded board: prints a boot log, offers a shell
    prompt and answers a few commands, so the full console path can be
    exercised on any OS without hardware.
    """

    PROMPT = "board> "

    def __init__(self, name: str) -> None:
        self.name = name
        self.booted_at = time.monotonic()
        self._line = ""

    def boot_banner(self) -> str:
        return (
            "\r\n[    0.000000] TargetHub virtual board booting\r\n"
            f"[    0.010000] Machine model: {self.name}\r\n"
            "[    0.120000] console: ttyS0 ready\r\n"
            "[simulated] serial console ready\r\n"
            f"{self.PROMPT}"
        )

    def feed(self, text: str) -> str:
        output = []
        for char in text:
            if char in "\r\n":
                command = self._line.strip()
                self._line = ""
                output.append("\r\n")
                if command:
                    output.append(self._respond(command))
                output.append(self.PROMPT)
            elif char in "\x7f\b":
                if self._line:
                    self._line = self._line[:-1]
                    output.append("\b \b")
            elif char == "\x03":
                self._line = ""
                output.append(f"^C\r\n{self.PROMPT}")
            else:
                self._line += char
                output.append(char)
        return "".join(output)

    def _respond(self, command: str) -> str:
        name, _, rest = command.partition(" ")
        if name == "help":
            return "commands: help, version, uptime, echo <text>, reboot\r\n"
        if name == "version":
            return f"TargetHub virtual board {AGENT_VERSION}\r\n"
        if name == "uptime":
            return f"up {time.monotonic() - self.booted_at:.1f}s\r\n"
        if name == "echo":
            return f"{rest}\r\n"
        if name == "reboot":
            self.booted_at = time.monotonic()
            return "rebooting...\r\n" + self.boot_banner().rstrip(self.PROMPT)
        return f"{name}: command not found\r\n"


class SerialChannel:
    """One open serial device with a background reader feeding a bounded buffer."""

    def __init__(self, resource_id: str, session_id: str, path: str, port=None, board: VirtualBoard | None = None):
        self.resource_id = resource_id
        self.session_id = session_id
        self.path = path
        self.port = port
        self.board = board
        self._buffer = bytearray()
        self.dropped = 0
        self._cond = threading.Condition()
        self._closed = threading.Event()
        self.last_activity = time.monotonic()
        self._reader: threading.Thread | None = None
        if board is not None:
            self._append(board.boot_banner().encode("utf-8"))
        elif port is not None:
            self._reader = threading.Thread(target=self._read_loop, name=f"serial-{path}", daemon=True)
            self._reader.start()

    @property
    def simulated(self) -> bool:
        return self.board is not None

    def _append(self, data: bytes) -> None:
        if not data:
            return
        with self._cond:
            self._buffer.extend(data)
            overflow = len(self._buffer) - SERIAL_BUFFER_BYTES
            if overflow > 0:
                del self._buffer[:overflow]
                self.dropped += overflow
            self._cond.notify_all()

    def _read_loop(self) -> None:
        while not self._closed.is_set():
            try:
                data = self.port.read(4096, 0.2)
            except (OSError, ValueError) as exc:
                if not self._closed.is_set():
                    log.warning("serial read on %s failed: %s", self.path, exc)
                    self._append(f"\r\n[targethub] serial read error: {exc}\r\n".encode())
                    self._closed.wait(1.0)
                continue
            except Exception as exc:  # pragma: no cover - pyserial specific errors
                if not self._closed.is_set():
                    log.warning("serial read on %s failed: %s", self.path, exc)
                    self._closed.wait(1.0)
                continue
            self._append(data)

    def read(self, size: int, wait: float) -> tuple[bytes, int]:
        self.last_activity = time.monotonic()
        deadline = time.monotonic() + max(0.0, wait)
        with self._cond:
            while not self._buffer and not self._closed.is_set():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                self._cond.wait(remaining)
            # Coalesce a burst: once data arrives, linger briefly for the rest of it.
            linger_until = min(deadline, time.monotonic() + SERIAL_COALESCE_SECONDS)
            while self._buffer and len(self._buffer) < size and not self._closed.is_set():
                before = len(self._buffer)
                remaining = linger_until - time.monotonic()
                if remaining <= 0:
                    break
                self._cond.wait(remaining)
                if len(self._buffer) == before:
                    break
            data = bytes(self._buffer[:size])
            del self._buffer[: len(data)]
            dropped, self.dropped = self.dropped, 0
        return data, dropped

    def write(self, data: bytes) -> int:
        self.last_activity = time.monotonic()
        if self.board is not None:
            self._append(self.board.feed(data.decode("utf-8", errors="replace")).encode("utf-8"))
            return len(data)
        return self.port.write(data)

    def close(self) -> None:
        self._closed.set()
        with self._cond:
            self._cond.notify_all()
        if self.port is not None:
            try:
                self.port.close()
            except Exception as exc:  # noqa: BLE001 - best effort
                log.debug("serial close failed: %s", exc)
        if self._reader is not None:
            self._reader.join(timeout=2)


class SerialRuntime:
    """Serial channels keyed by resource; at most one session owns a device at a time."""

    def __init__(self, allowed_paths=None, idle_timeout: float = DEFAULT_SERIAL_IDLE_TIMEOUT) -> None:
        self._channels: dict[str, SerialChannel] = {}
        self._lock = threading.Lock()
        # Callable returning the set of device paths this agent may open (None: any path).
        self._allowed_paths = allowed_paths
        self.idle_timeout = idle_timeout

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
    def _as_text(value: object) -> str:
        return value if isinstance(value, str) else str(value)

    @staticmethod
    def _read_size(params: dict) -> int:
        size = int(params.get("size", 4096))
        return max(1, min(size, MAX_SERIAL_READ_SIZE))

    def _path_allowed(self, path: str) -> bool:
        if self._allowed_paths is not None:
            return path in self._allowed_paths()
        if IS_WINDOWS:  # pragma: no cover
            return path.upper().startswith(("COM", "\\\\.\\COM"))
        return path.startswith("/dev/")

    def close_all(self) -> None:
        with self._lock:
            channels = list(self._channels.values())
            self._channels.clear()
        for channel in channels:
            channel.close()

    def reap_idle(self) -> int:
        """Close channels nobody has used for ``idle_timeout`` seconds (safety net)."""
        cutoff = time.monotonic() - self.idle_timeout
        with self._lock:
            stale = [key for key, channel in self._channels.items() if channel.last_activity < cutoff]
            channels = [self._channels.pop(key) for key in stale]
        for channel in channels:
            log.info("closing idle serial channel %s (session %s)", channel.path, channel.session_id)
            channel.close()
        return len(channels)

    def execute(self, operation_payload: dict) -> dict:
        operation = str(operation_payload.get("operation", "")).strip().lower()
        params = operation_payload.get("params") or {}
        session_id = str(operation_payload.get("session_id", ""))
        resource_id = str(operation_payload.get("resource_id", ""))
        if not session_id or not resource_id:
            return {"success": False, "message": "Operation is missing session/resource binding"}

        mode = {"mode": "simulated"} if self._is_simulated(operation_payload) else {}
        path = self._resolve_path(operation_payload)

        if operation == "open":
            return self._open(operation_payload, session_id, resource_id, path, mode)

        if operation == "close":
            with self._lock:
                channel = self._channels.get(resource_id)
                if channel is None or channel.session_id != session_id:
                    return {"success": True, "message": "Serial connection already closed", "data": {"path": path, **mode}}
                self._channels.pop(resource_id)
            channel.close()
            return {"success": True, "message": "Serial connection closed", "data": {"path": path, **mode}}

        with self._lock:
            channel = self._channels.get(resource_id)
        if channel is None or channel.session_id != session_id:
            return {"success": False, "message": "Serial connection is not open"}

        if operation == "write":
            payload = self._as_text(params.get("text", "")).encode("utf-8")
            try:
                written = channel.write(payload)
            except Exception as exc:  # noqa: BLE001 - surface any transport error
                return {"success": False, "message": f"Failed to write serial data: {exc}"}
            return {"success": True, "message": "Serial data written", "data": {"bytes_written": written, "path": path, **mode}}

        if operation == "read":
            metadata = operation_payload.get("resource_metadata") or {}
            if "wait_ms" in params:
                wait = int(params.get("wait_ms") or 0) / 1000.0
            else:
                wait = float(metadata.get("timeout", 0.2))
            wait = max(0.0, min(wait, MAX_SERIAL_READ_WAIT_SECONDS))
            data, dropped = channel.read(self._read_size(params), wait)
            return {
                "success": True,
                "message": "Serial data read",
                "data": {
                    "bytes_read": len(data),
                    "data_text": data.decode("utf-8", errors="replace"),
                    "data_hex": data.hex(),
                    "dropped_bytes": dropped,
                    "path": path,
                    **mode,
                },
            }

        return {"success": False, "message": f"Unsupported serial operation '{operation}'"}

    def _open(self, payload: dict, session_id: str, resource_id: str, path: str, mode: dict) -> dict:
        with self._lock:
            existing = self._channels.get(resource_id)
            if existing is not None and existing.session_id == session_id:
                return {"success": True, "message": "Serial connection already open", "data": {"path": path, **mode}}
            if existing is not None:
                # The hub only dispatches for active sessions, so a different
                # owner means the previous session ended: take the port over.
                log.info("serial %s: session %s replaces %s", path, session_id, existing.session_id)
                self._channels.pop(resource_id)
        if existing is not None:
            existing.close()

        metadata = payload.get("resource_metadata") or {}
        if mode:
            channel = SerialChannel(resource_id, session_id, path, board=VirtualBoard(path))
        else:
            if not self._path_allowed(path):
                return {"success": False, "message": f"Serial path '{path}' is not allowed on this Agent"}
            try:
                baudrate = int(metadata.get("baudrate", 115200))
            except (TypeError, ValueError):
                baudrate = 115200
            if baudrate not in SUPPORTED_BAUDRATES:
                return {"success": False, "message": f"Unsupported baudrate {baudrate}"}
            try:
                port = open_serial_port(path, baudrate)
            except Exception as exc:  # noqa: BLE001 - OSError or pyserial SerialException
                return {"success": False, "message": f"Failed to open serial connection: {exc}"}
            channel = SerialChannel(resource_id, session_id, path, port=port)
        with self._lock:
            self._channels[resource_id] = channel
        return {"success": True, "message": "Serial connection opened", "data": {"path": path, **mode}}


# --------------------------------------------------------------------------- power


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


class DDPowerClient:
    """Client for the DD Endpoint Control REST API (relay endpoints over MQTT).

    A control request returns 202 once the command is *published*; the
    device confirms asynchronously, so state changes are confirmed by polling
    the status endpoint until ``current_state`` matches.
    """

    def __init__(self, metadata: dict) -> None:
        self.base_url = str(metadata.get("base_url", "")).rstrip("/")
        if not self.base_url.startswith(("http://", "https://")):
            raise ValueError("DD power requires base_url (http:// or https://)")
        self.hub_mac = str(metadata.get("hub_mac", "")).strip()
        if not self.hub_mac:
            raise ValueError("DD power requires hub_mac")
        self.node_id = int(metadata["node_id"])
        self.endpoint = int(metadata["endpoint"])
        key_env = metadata.get("api_key_env")
        self.api_key = os.environ.get(str(key_env), "") if key_env else str(metadata.get("api_key", ""))
        self.timeout = max(1.0, min(float(metadata.get("timeout", 10)), 60.0))
        self.confirm_timeout = max(0.0, min(float(metadata.get("confirm_timeout", 10)), 120.0))
        self.cycle_delay = max(0.5, min(float(metadata.get("cycle_delay", 3)), 60.0))

    def _call(self, method: str, path: str, body: dict | None = None) -> tuple[int, dict]:
        headers = {"Accept": "application/json"}
        if self.api_key:
            headers["X-API-Key"] = self.api_key
        data = None
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(self.base_url + path, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=self.timeout, context=_ssl_context) as response:
                raw = response.read().decode("utf-8")
                return response.status, (json.loads(raw) if raw else {})
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="replace")
            try:
                payload = json.loads(raw) if raw else {}
            except json.JSONDecodeError:
                payload = {"message": raw[:200]}
            return exc.code, payload

    @staticmethod
    def _error(status: int, payload: dict) -> str:
        reason = {
            400: "DD rejected the request (check hub_mac/node_id/endpoint)",
            401: "DD API key missing or rejected",
            404: "DD node or endpoint not found",
            423: "DD hub is under emergency lock; control is blocked",
            500: "DD failed to publish the command",
        }.get(status, f"DD returned HTTP {status}")
        detail = payload.get("message") or payload.get("error")
        return f"{reason}: {detail}" if detail else reason

    def _status_path(self) -> str:
        mac = urllib.parse.quote(self.hub_mac, safe="")
        return f"/api/hubs/{mac}/nodes/{self.node_id}/endpoints/{self.endpoint}"

    def status(self) -> dict:
        try:
            status, payload = self._call("GET", self._status_path())
        except (urllib.error.URLError, OSError) as exc:
            return {"success": False, "message": f"DD unreachable: {exc}"}
        if status != 200:
            return {"success": False, "message": self._error(status, payload)}
        endpoint = payload.get("endpoint") or {}
        node = payload.get("node") or {}
        state = str(endpoint.get("current_state", "unknown")).lower()
        return {
            "success": True,
            "message": "Power status",
            "data": {
                "state": state if state in {"on", "off"} else "unknown",
                "updated_at": endpoint.get("updated_at"),
                "endpoint_name": endpoint.get("endpoint_name"),
                "node_connected": node.get("is_connected"),
                "emergency_active": bool(payload.get("emergency_active")),
            },
        }

    def set_state(self, on: bool) -> dict:
        wanted = "ON" if on else "OFF"
        body = {"hub_mac": self.hub_mac, "node_id": self.node_id, "endpoint": self.endpoint, "state": wanted}
        try:
            status, payload = self._call("POST", "/api/endpoints/control", body)
        except (urllib.error.URLError, OSError) as exc:
            return {"success": False, "message": f"DD unreachable: {exc}"}
        if status not in (200, 202):
            return {"success": False, "message": self._error(status, payload)}
        deadline = time.monotonic() + self.confirm_timeout
        last = None
        while True:
            current = self.status()
            if current.get("success"):
                last = current["data"]
                if last["state"] == wanted.lower():
                    return {"success": True, "message": f"Power {wanted.lower()} confirmed", "data": {**last, "confirmed": True}}
            if time.monotonic() >= deadline:
                break
            time.sleep(0.5)
        return {
            "success": True,
            "message": f"Power {wanted.lower()} accepted; device has not confirmed yet",
            "data": {**(last or {}), "state": (last or {}).get("state", "unknown"), "confirmed": False, "requested": wanted.lower()},
        }

    def execute(self, operation: str) -> dict:
        if operation == "status":
            return self.status()
        if operation in {"on", "off"}:
            return self.set_state(operation == "on")
        if operation in {"cycle", "reset"}:
            off = self.set_state(False)
            if not off["success"]:
                return off
            time.sleep(self.cycle_delay)
            on = self.set_state(True)
            if on["success"]:
                on["message"] = f"Power {operation} complete" + ("" if on["data"].get("confirmed") else " (on not yet confirmed)")
            return on
        return {"success": False, "message": f"Unsupported power operation '{operation}'"}


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
        if str(metadata.get("backend", "")) == "dd":
            try:
                return DDPowerClient(metadata).execute(operation)
            except (KeyError, TypeError, ValueError) as exc:
                return {"success": False, "message": f"Invalid DD power configuration: {exc}"}
        if IS_WINDOWS:  # pragma: no cover
            return {"success": False, "message": "GPIO power is only supported on Linux agents"}
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


# --------------------------------------------------------------------------- deploy


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


# --------------------------------------------------------------------------- dispatch


class OperationRouter:
    """Dispatch hub operations to the runtime for their resource type."""

    def __init__(self, config: dict) -> None:
        self.config = config
        self._known_serial_paths: set[str] = set()
        self.serial = SerialRuntime(
            allowed_paths=self.allowed_serial_paths,
            idle_timeout=float(config.get("serial_idle_timeout", DEFAULT_SERIAL_IDLE_TIMEOUT)),
        )
        self.power = PowerRuntime()
        self.deploy = DeployRuntime()
        self._resource_locks: dict[str, threading.Lock] = {}
        self._locks_guard = threading.Lock()

    def remember_resources(self, resources: list[dict]) -> None:
        """Record serial devices from the latest discovery; only these may be opened."""
        self._known_serial_paths = {
            str((item.get("metadata") or {}).get("path") or item["resource_key"])
            for item in resources
            if item.get("resource_type") == "serial"
        }

    def allowed_serial_paths(self) -> set[str]:
        configured = {
            str((item.get("metadata") or {}).get("path") or item.get("resource_key"))
            for item in self.config.get("resources", [])
            if item.get("resource_type") == "serial"
        }
        return self._known_serial_paths | configured

    def _local_metadata(self, resource_key: str) -> dict | None:
        # Power/deploy settings come from the local config only; the hub's copy is not trusted.
        for item in self.config.get("resources", []):
            if item.get("resource_key") == resource_key:
                return item.get("metadata") or {}
        return None

    def _lock_for(self, resource_key: str) -> threading.Lock:
        with self._locks_guard:
            return self._resource_locks.setdefault(resource_key, threading.Lock())

    def execute(self, payload: dict) -> dict:
        resource_type = str(payload.get("resource_type", ""))
        operation = str(payload.get("operation", "")).strip().lower()
        params = payload.get("params") or {}
        if resource_type == "serial":
            return self.serial.execute(payload)
        if resource_type in {"power", "reset", "deploy"}:
            resource_key = str(payload.get("resource_key", ""))
            metadata = self._local_metadata(resource_key)
            if metadata is None:
                return {"success": False, "message": "Resource is not configured on this Agent"}
            with self._lock_for(resource_key):
                if resource_type == "deploy":
                    return self.deploy.execute(operation, params, metadata)
                return self.power.execute(operation, metadata)
        return {"success": False, "message": f"Unsupported resource type '{resource_type}'"}


def run_operation(config: dict, router: OperationRouter, operation: dict, request_timeout: int) -> None:
    try:
        try:
            execution = router.execute(operation)
        except Exception as exc:  # noqa: BLE001 - report instead of letting the hub time out
            execution = {"success": False, "message": f"Agent error: {exc.__class__.__name__}: {exc}"}
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


class AgentLoop:
    """Heartbeat thread + operation poller feeding a bounded worker pool."""

    def __init__(self, config: dict, router: OperationRouter) -> None:
        self.config = config
        self.router = router
        self.interval = max(5, int(config.get("heartbeat_interval", DEFAULT_INTERVAL)))
        self.request_timeout = max(5, int(config.get("request_timeout", DEFAULT_REQUEST_TIMEOUT)))
        self.poll_wait = max(1, min(int(config.get("operation_poll_wait_seconds", DEFAULT_OPERATION_POLL_WAIT_SECONDS)), 25))
        self.max_workers = max(1, min(int(config.get("max_concurrent_operations", DEFAULT_MAX_CONCURRENT_OPERATIONS)), 32))
        self._inflight = threading.Semaphore(self.max_workers)
        self._pool = ThreadPoolExecutor(max_workers=self.max_workers, thread_name_prefix="op")
        self._secrets = [str(config.get("credential", ""))]

    def _warn(self, message: str) -> None:
        log.warning(_redact(message, self._secrets))

    def heartbeat_loop(self) -> None:
        delay = 0
        while not _stop.is_set():
            try:
                resources = discover_resources(self.config)
                self.router.remember_resources(resources)
                heartbeat(self.config, request_timeout=self.request_timeout, resources=resources)
                self.router.serial.reap_idle()
                delay = 0
                sd_notify("WATCHDOG=1")
                _stop.wait(self.interval)
            except Exception as exc:  # keep the service alive through transient failures
                delay = _next_retry_delay(delay)
                self._warn(f"heartbeat error: {exc}; retrying in {delay}s")
                _stop.wait(_jittered(delay))

    def _run(self, operation: dict) -> None:
        try:
            run_operation(self.config, self.router, operation, self.request_timeout)
        finally:
            self._inflight.release()

    def poll_loop(self) -> None:
        delay = 0
        while not _stop.is_set():
            if not self._inflight.acquire(timeout=1):
                continue
            try:
                result = poll_operation(
                    self.config,
                    wait_seconds=self.poll_wait,
                    request_timeout=max(self.request_timeout, self.poll_wait + 10),
                )
                delay = 0
            except Exception as exc:
                self._inflight.release()
                delay = _next_retry_delay(delay)
                self._warn(f"operation poll error: {exc}; retrying in {delay}s")
                _stop.wait(_jittered(delay))
                continue
            operation = result.get("operation")
            if not operation:
                self._inflight.release()
                continue
            self._pool.submit(self._run, operation)

    def run(self) -> None:
        threads = [
            threading.Thread(target=self.heartbeat_loop, name="heartbeat", daemon=True),
            threading.Thread(target=self.poll_loop, name="poller", daemon=True),
        ]
        for thread in threads:
            thread.start()
        sd_notify("READY=1")
        while not _stop.wait(1):
            pass
        for thread in threads:
            thread.join(timeout=self.poll_wait + 15)
        self._pool.shutdown(wait=True, cancel_futures=True)


def main() -> int:
    ensure_supported_platform()
    parser = argparse.ArgumentParser(description="TargetHub Agent")
    parser.add_argument("--config", default=DEFAULT_CONFIG_PATH)
    parser.add_argument("--insecure", action="store_true", help="allow a plain http:// TargetHub URL")
    parser.add_argument("--version", action="version", version=f"targethub-agent {AGENT_VERSION}")
    args = parser.parse_args()
    # journald / the Windows task log capture stderr and add timestamps.
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s", stream=sys.stderr)
    signal.signal(signal.SIGTERM, _handle_stop)
    signal.signal(signal.SIGINT, _handle_stop)
    if hasattr(signal, "SIGBREAK"):  # pragma: no cover - Windows console close
        signal.signal(signal.SIGBREAK, _handle_stop)

    config_path = Path(args.config)
    config = load_config(config_path)
    validate_hub_url(config, args.insecure)
    configure_tls(config)
    request_timeout = max(5, int(config.get("request_timeout", DEFAULT_REQUEST_TIMEOUT)))

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

    log.info(
        "TargetHub Agent %s running as %s on %s (serial backend: %s)",
        AGENT_VERSION,
        config["agent_id"],
        sys.platform,
        "pyserial" if _pyserial is not None else "termios",
    )
    router = OperationRouter(config)
    try:
        AgentLoop(config, router).run()
    finally:
        sd_notify("STOPPING=1")
        router.serial.close_all()
    log.info("TargetHub Agent stopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
