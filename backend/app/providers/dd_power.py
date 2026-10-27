"""DD Endpoint Control API power driver (server-hosted; no Agent required).

The DD system switches relay *endpoints* on *nodes* behind a *hub* and
publishes each command over MQTT. A control request returns 202 once the
command is published; the device confirms asynchronously. This driver
therefore confirms every change by polling the status endpoint until the
reported ``current_state`` matches, and says so when it could not confirm.

DD only switches power, so ``reset`` and ``cycle`` are both OFF -> wait -> ON.

Configuration (capability ``provider_config``)::

    {
      "driver": "dd",
      "base_url": "http://dd-server:5003",
      "hub_mac": "AA:BB:CC:DD:EE:FF",
      "node_id": 1,
      "endpoint": 2,
      "api_key_env": "TARGETHUB_DD_API_KEY",   # optional; key lives in the hub env
      "cycle_delay_seconds": 3,
      "confirm_timeout_seconds": 10,
      "timeout_seconds": 10
    }
"""

from __future__ import annotations

import json
import os
import re
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any

from app.providers.base import ProviderOperationResult, TargetProvider

MAC_PATTERN = re.compile(r"^[0-9A-Fa-f]{2}([:-]?[0-9A-Fa-f]{2}){5}$")
ENV_NAME_PATTERN = re.compile(r"^[A-Z_][A-Z0-9_]{0,127}$")
DD_OPERATIONS = ("status", "on", "off", "cycle", "reset")

DD_ERRORS = {
    400: "DD rejected the request (check hub MAC, node ID and endpoint)",
    401: "DD API key is missing or was rejected",
    404: "DD node or endpoint not found",
    423: "DD hub is under emergency lock; power control is blocked",
    500: "DD failed to publish the command",
}


def _number(value: Any, name: str, minimum: float, maximum: float, default: float) -> float:
    if value is None or value == "":
        return default
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"DD power '{name}' must be a number") from exc
    if not minimum <= parsed <= maximum:
        raise ValueError(f"DD power '{name}' must be between {minimum} and {maximum}")
    return parsed


def _integer(value: Any, name: str, minimum: int) -> int:
    try:
        parsed = int(str(value).strip())
    except (TypeError, ValueError) as exc:
        raise ValueError(f"DD power '{name}' must be an integer") from exc
    if parsed < minimum:
        raise ValueError(f"DD power '{name}' must be >= {minimum}")
    return parsed


@dataclass(slots=True, frozen=True)
class DDPowerConfig:
    base_url: str
    hub_mac: str
    node_id: int
    endpoint: int
    api_key_env: str | None = None
    timeout_seconds: float = 10.0
    confirm_timeout_seconds: float = 10.0
    cycle_delay_seconds: float = 3.0
    poll_interval_seconds: float = 0.5
    tls_skip_verify: bool = False


def build_dd_config(cfg: dict[str, Any]) -> DDPowerConfig:
    base_url = str(cfg.get("base_url", "")).strip().rstrip("/")
    parsed = urllib.parse.urlparse(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("DD power requires 'base_url' like http://dd-server:5003")
    hub_mac = str(cfg.get("hub_mac", "")).strip().upper()
    if not MAC_PATTERN.fullmatch(hub_mac):
        raise ValueError("DD power 'hub_mac' must be a MAC address like AA:BB:CC:DD:EE:FF")
    api_key_env = cfg.get("api_key_env")
    if api_key_env:
        api_key_env = str(api_key_env).strip()
        if not ENV_NAME_PATTERN.fullmatch(api_key_env):
            raise ValueError("DD power 'api_key_env' must be an environment variable name")
    if "api_key" in cfg:
        raise ValueError("Do not store the DD API key in TargetHub; set 'api_key_env' and put the key in the server environment")
    return DDPowerConfig(
        base_url=base_url,
        hub_mac=hub_mac,
        node_id=_integer(cfg.get("node_id"), "node_id", 0),
        endpoint=_integer(cfg.get("endpoint"), "endpoint", 0),
        api_key_env=api_key_env or None,
        timeout_seconds=_number(cfg.get("timeout_seconds"), "timeout_seconds", 1, 60, 10),
        confirm_timeout_seconds=_number(cfg.get("confirm_timeout_seconds"), "confirm_timeout_seconds", 0, 120, 10),
        cycle_delay_seconds=_number(cfg.get("cycle_delay_seconds"), "cycle_delay_seconds", 0.5, 120, 3),
        poll_interval_seconds=_number(cfg.get("poll_interval_seconds"), "poll_interval_seconds", 0.05, 5, 0.5),
        tls_skip_verify=bool(cfg.get("tls_skip_verify", False)),
    )


class DDPowerProvider(TargetProvider):
    capability_type = "power"

    def __init__(self, provider_key: str, config: DDPowerConfig) -> None:
        self.provider_key = provider_key
        self.config = config

    def operations(self) -> list[str]:
        return ["health", *DD_OPERATIONS]

    # ---------------------------------------------------------------- http

    def _headers(self) -> dict[str, str]:
        headers = {"Accept": "application/json", "Content-Type": "application/json"}
        if self.config.api_key_env:
            key = os.getenv(self.config.api_key_env, "")
            if not key:
                raise ValueError(f"DD API key environment variable '{self.config.api_key_env}' is not set on the server")
            headers["X-API-Key"] = key
        return headers

    def _call(self, method: str, path: str, body: dict | None = None) -> tuple[int, dict]:
        request = urllib.request.Request(
            self.config.base_url + path,
            data=json.dumps(body).encode("utf-8") if body is not None else None,
            headers=self._headers(),
            method=method,
        )
        context = None
        if self.config.tls_skip_verify and self.config.base_url.startswith("https://"):
            context = ssl._create_unverified_context()  # noqa: S323 - explicit opt-out
        try:
            with urllib.request.urlopen(request, timeout=self.config.timeout_seconds, context=context) as response:
                raw = response.read().decode("utf-8")
                return response.status, (json.loads(raw) if raw else {})
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="replace")
            try:
                payload = json.loads(raw) if raw else {}
            except json.JSONDecodeError:
                payload = {"message": raw[:200]}
            return exc.code, payload if isinstance(payload, dict) else {}

    def _failure(self, status: int, payload: dict) -> ProviderOperationResult:
        reason = DD_ERRORS.get(status, f"DD returned HTTP {status}")
        detail = payload.get("message") or payload.get("error")
        return ProviderOperationResult(
            False, f"{reason}: {detail}" if detail else reason, {**self._meta(), "http_status": status}
        )

    def _meta(self) -> dict[str, Any]:
        return {
            "provider_key": self.provider_key,
            "mode": "dd",
            "hub_mac": self.config.hub_mac,
            "node_id": self.config.node_id,
            "endpoint": self.config.endpoint,
        }

    def _status_path(self) -> str:
        mac = urllib.parse.quote(self.config.hub_mac, safe="")
        return f"/api/hubs/{mac}/nodes/{self.config.node_id}/endpoints/{self.config.endpoint}"

    # ---------------------------------------------------------------- operations

    def status(self) -> ProviderOperationResult:
        try:
            code, payload = self._call("GET", self._status_path())
        except (urllib.error.URLError, OSError, ValueError) as exc:
            return ProviderOperationResult(False, f"DD server is unreachable: {exc}", self._meta())
        if code != 200:
            return self._failure(code, payload)
        endpoint = payload.get("endpoint") or {}
        node = payload.get("node") or {}
        state = str(endpoint.get("current_state", "")).strip().lower()
        state = state if state in {"on", "off"} else "unknown"
        return ProviderOperationResult(
            True,
            "Power status",
            {
                **self._meta(),
                "power": state,
                "state": state,
                "endpoint_name": endpoint.get("endpoint_name"),
                "updated_at": endpoint.get("updated_at"),
                "node_connected": node.get("is_connected"),
                "node_last_seen": node.get("last_seen"),
                "emergency_active": bool(payload.get("emergency_active")),
            },
        )

    def _set(self, on: bool) -> ProviderOperationResult:
        wanted = "ON" if on else "OFF"
        body = {
            "hub_mac": self.config.hub_mac,
            "node_id": self.config.node_id,
            "endpoint": self.config.endpoint,
            "state": wanted,
        }
        try:
            code, payload = self._call("POST", "/api/endpoints/control", body)
        except (urllib.error.URLError, OSError, ValueError) as exc:
            return ProviderOperationResult(False, f"DD server is unreachable: {exc}", self._meta())
        if code not in (200, 202):
            return self._failure(code, payload)
        if payload.get("emergency_active"):
            return ProviderOperationResult(False, DD_ERRORS[423], self._meta())

        deadline = time.monotonic() + self.config.confirm_timeout_seconds
        last: dict[str, Any] = {}
        while True:
            current = self.status()
            if current.success:
                last = current.data or {}
                if last.get("state") == wanted.lower():
                    return ProviderOperationResult(
                        True, f"Power {wanted.lower()} confirmed by device", {**last, "confirmed": True}
                    )
            if time.monotonic() >= deadline:
                break
            time.sleep(self.config.poll_interval_seconds)
        return ProviderOperationResult(
            True,
            f"Power {wanted.lower()} command accepted by DD; device has not confirmed yet",
            {**self._meta(), **last, "confirmed": False, "requested": wanted.lower()},
        )

    def _cycle(self, label: str, delay: float | None) -> ProviderOperationResult:
        off = self._set(False)
        if not off.success:
            return off
        time.sleep(self.config.cycle_delay_seconds if delay is None else delay)
        on = self._set(True)
        if not on.success:
            return on
        confirmed = bool((off.data or {}).get("confirmed")) and bool((on.data or {}).get("confirmed"))
        suffix = "" if confirmed else " (device confirmation pending)"
        return ProviderOperationResult(True, f"Power {label} complete{suffix}", {**(on.data or {}), "confirmed": confirmed})

    def health_check(self) -> ProviderOperationResult:
        result = self.status()
        if result.success:
            result.message = "DD power endpoint reachable"
        return result

    def execute(self, operation: str, params: dict[str, Any] | None = None) -> ProviderOperationResult:
        params = params or {}
        if operation == "status":
            return self.status()
        if operation in {"on", "off"}:
            return self._set(operation == "on")
        if operation in {"cycle", "reset"}:
            delay = params.get("delay_seconds")
            try:
                delay_value = None if delay is None else _number(delay, "delay_seconds", 0.5, 120, 3)
            except ValueError as exc:
                return ProviderOperationResult(False, str(exc))
            return self._cycle("reset" if operation == "reset" else "cycle", delay_value)
        return super().execute(operation, params)
