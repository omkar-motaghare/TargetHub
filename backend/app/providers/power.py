from __future__ import annotations

import json
import os
import re
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Any

from app.providers.base import ProviderOperationResult, TargetProvider

POWER_MODE_SIMULATED = "simulated"
POWER_MODE_REAL = "real"
POWER_ALLOWED_MODES = {POWER_MODE_SIMULATED, POWER_MODE_REAL}
POWER_ALLOWED_COMMANDS = {"status", "on", "off", "reset", "cycle"}
POWER_ALLOWED_AUTH_TYPES = {"none", "bearer", "basic"}
ENV_NAME_PATTERN = re.compile(r"^[A-Z_][A-Z0-9_]{0,127}$")
OUTLET_ID_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{1,64}$")


def _as_float(value: object, *, name: str, minimum: float, maximum: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"power provider '{name}' must be a number") from exc
    if parsed < minimum or parsed > maximum:
        raise ValueError(f"power provider '{name}' must be between {minimum} and {maximum}")
    return parsed


def _as_env_name(value: object, *, name: str) -> str:
    candidate = str(value or "").strip()
    if not ENV_NAME_PATTERN.fullmatch(candidate):
        raise ValueError(f"power provider '{name}' must be a valid environment variable name")
    return candidate


def _as_mode(value: object) -> str:
    candidate = str(value or POWER_MODE_SIMULATED).strip().lower()
    if candidate not in POWER_ALLOWED_MODES:
        allowed = ", ".join(sorted(POWER_ALLOWED_MODES))
        raise ValueError(f"power provider mode must be one of: {allowed}")
    return candidate


def _as_auth_type(value: object) -> str:
    candidate = str(value or "none").strip().lower()
    if candidate not in POWER_ALLOWED_AUTH_TYPES:
        allowed = ", ".join(sorted(POWER_ALLOWED_AUTH_TYPES))
        raise ValueError(f"power provider auth_type must be one of: {allowed}")
    return candidate


def _as_bool(value: object, *, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"invalid boolean value '{value}'")


@dataclass(slots=True)
class PowerProviderConfig:
    provider_key: str
    provider_config: dict[str, Any] = field(default_factory=dict)
    mode: str = POWER_MODE_SIMULATED
    controller_url: str | None = None
    outlet_id: str | None = None
    timeout_seconds: float = 3.0
    cycle_delay_seconds: float = 1.0
    auth_type: str = "none"
    bearer_token_env: str | None = None
    basic_username_env: str | None = None
    basic_password_env: str | None = None
    tls_skip_verify: bool = False
    supports_cycle_command: bool = True


def build_power_provider_config(provider_key: str, provider_config: dict[str, Any] | None) -> PowerProviderConfig:
    cfg = provider_config or {}
    mode = _as_mode(cfg.get("mode"))
    timeout_seconds = _as_float(
        cfg.get("timeout_seconds", 3.0),
        name="timeout_seconds",
        minimum=0.2,
        maximum=30.0,
    )
    cycle_delay_seconds = _as_float(
        cfg.get("cycle_delay_seconds", 1.0),
        name="cycle_delay_seconds",
        minimum=0.0,
        maximum=30.0,
    )

    if mode == POWER_MODE_SIMULATED:
        return PowerProviderConfig(
            provider_key=provider_key,
            provider_config=cfg,
            mode=mode,
            timeout_seconds=timeout_seconds,
            cycle_delay_seconds=cycle_delay_seconds,
        )

    controller_url = str(cfg.get("controller_url", "")).strip()
    if not controller_url:
        raise ValueError("power provider real mode requires 'controller_url'")
    parsed = urllib.parse.urlparse(controller_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("power provider 'controller_url' must be a valid http(s) URL")

    outlet_id = str(cfg.get("outlet_id", "")).strip()
    if not OUTLET_ID_PATTERN.fullmatch(outlet_id):
        raise ValueError(
            "power provider 'outlet_id' must match ^[A-Za-z0-9._:-]{1,64}$"
        )

    auth_type = _as_auth_type(cfg.get("auth_type"))
    bearer_token_env = None
    basic_username_env = None
    basic_password_env = None
    if auth_type == "bearer":
        bearer_token_env = _as_env_name(cfg.get("bearer_token_env"), name="bearer_token_env")
    elif auth_type == "basic":
        basic_username_env = _as_env_name(cfg.get("basic_username_env"), name="basic_username_env")
        basic_password_env = _as_env_name(cfg.get("basic_password_env"), name="basic_password_env")

    tls_skip_verify = _as_bool(cfg.get("tls_skip_verify"), default=False)
    supports_cycle_command = _as_bool(cfg.get("supports_cycle_command"), default=True)

    return PowerProviderConfig(
        provider_key=provider_key,
        provider_config=cfg,
        mode=mode,
        controller_url=controller_url.rstrip("/"),
        outlet_id=outlet_id,
        timeout_seconds=timeout_seconds,
        cycle_delay_seconds=cycle_delay_seconds,
        auth_type=auth_type,
        bearer_token_env=bearer_token_env,
        basic_username_env=basic_username_env,
        basic_password_env=basic_password_env,
        tls_skip_verify=tls_skip_verify,
        supports_cycle_command=supports_cycle_command,
    )


class PowerProvider(TargetProvider):
    """Power control provider with simulated + real HTTP controller modes.

    Simulated mode is the default and remains available for development.
    Real mode performs authenticated HTTP requests to a power-controller API:

    - `GET  {controller_url}/v1/outlets/{outlet_id}/status`
    - `POST {controller_url}/v1/outlets/{outlet_id}/on|off|reset|cycle`
    """

    capability_type = "power"

    # Simulated power state shared per physical device (provider_key).
    _state: dict[str, str] = {}

    def __init__(self, config: PowerProviderConfig) -> None:
        self.config = config
        self.provider_key = config.provider_key

    def operations(self) -> list[str]:
        return ["health", "status", "on", "off", "reset", "cycle"]

    def _current(self) -> str:
        return self._state.get(self.provider_key, "off")

    def _set(self, value: str) -> None:
        self._state[self.provider_key] = value

    def _is_real(self) -> bool:
        return self.config.mode == POWER_MODE_REAL

    def _mode_label(self) -> str:
        return POWER_MODE_REAL if self._is_real() else POWER_MODE_SIMULATED

    def _base_metadata(self) -> dict[str, Any]:
        payload = {
            "provider_key": self.provider_key,
            "mode": self._mode_label(),
        }
        if self._is_real():
            payload["outlet_id"] = self.config.outlet_id
        return payload

    def _validated_params(self, operation: str, params: dict[str, Any] | None) -> dict[str, Any]:
        if operation not in POWER_ALLOWED_COMMANDS:
            return {}
        params = params or {}
        if operation == "cycle":
            allowed = {"delay_seconds"}
        else:
            allowed = set()
        invalid = sorted(set(params) - allowed)
        if invalid:
            joined = ", ".join(invalid)
            raise ValueError(f"Unsupported parameters for power operation '{operation}': {joined}")
        return params

    def _build_headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if not self._is_real():
            return headers
        if self.config.auth_type == "none":
            return headers
        if self.config.auth_type == "bearer":
            assert self.config.bearer_token_env is not None
            token = os.getenv(self.config.bearer_token_env, "")
            if not token:
                raise ValueError(
                    f"Power controller token is missing in env '{self.config.bearer_token_env}'"
                )
            headers["Authorization"] = f"Bearer {token}"
            return headers
        if self.config.auth_type == "basic":
            assert self.config.basic_username_env is not None
            assert self.config.basic_password_env is not None
            username = os.getenv(self.config.basic_username_env, "")
            password = os.getenv(self.config.basic_password_env, "")
            if not username or not password:
                raise ValueError(
                    "Power controller basic-auth credentials are missing in configured environment variables"
                )
            import base64

            encoded = base64.b64encode(f"{username}:{password}".encode()).decode("ascii")
            headers["Authorization"] = f"Basic {encoded}"
            return headers
        raise ValueError(f"Unsupported power auth_type '{self.config.auth_type}'")

    def _request(self, method: str, path: str, body: dict[str, Any] | None = None) -> ProviderOperationResult:
        assert self.config.controller_url is not None
        if ".." in path:
            return ProviderOperationResult(False, "Unsafe power-controller path rejected")
        url = f"{self.config.controller_url}{path}"
        data = None if body is None else json.dumps(body).encode("utf-8")
        try:
            request = urllib.request.Request(
                url,
                data=data,
                headers=self._build_headers(),
                method=method,
            )
            context = None
            if self.config.tls_skip_verify and url.lower().startswith("https://"):
                context = ssl._create_unverified_context()  # noqa: S323 - explicit opt-out flag
            with urllib.request.urlopen(
                request,
                timeout=self.config.timeout_seconds,
                context=context,
            ) as response:
                payload = response.read().decode("utf-8")
                data = json.loads(payload) if payload else {}
                if not isinstance(data, dict):
                    return ProviderOperationResult(False, "Power controller returned an invalid response")
                return ProviderOperationResult(True, "Power controller request succeeded", data)
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            return ProviderOperationResult(False, f"Power controller rejected request ({exc.code}): {detail}")
        except urllib.error.URLError as exc:
            return ProviderOperationResult(False, f"Power controller is unreachable: {exc.reason}")
        except TimeoutError:
            return ProviderOperationResult(False, "Power controller request timed out")
        except json.JSONDecodeError:
            return ProviderOperationResult(False, "Power controller returned malformed JSON")
        except ValueError as exc:
            # Validation errors from _build_headers/config checks.
            return ProviderOperationResult(False, str(exc))

    def _real_status(self) -> ProviderOperationResult:
        assert self.config.outlet_id is not None
        response = self._request("GET", f"/v1/outlets/{self.config.outlet_id}/status")
        if not response.success:
            return response
        data = response.data or {}
        state = str(data.get("power", "")).strip().lower()
        if state not in {"on", "off"}:
            if isinstance(data.get("is_on"), bool):
                state = "on" if data["is_on"] else "off"
            else:
                return ProviderOperationResult(False, "Power controller status response is missing power state")
        return ProviderOperationResult(
            True,
            "Power status",
            {**self._base_metadata(), "power": state},
        )

    def _real_command(self, command: str, *, delay_seconds: float | None = None) -> ProviderOperationResult:
        assert self.config.outlet_id is not None
        if command == "cycle" and not self.config.supports_cycle_command:
            off_result = self._request("POST", f"/v1/outlets/{self.config.outlet_id}/off", {})
            if not off_result.success:
                return off_result
            delay = self.config.cycle_delay_seconds if delay_seconds is None else delay_seconds
            time.sleep(max(0.0, delay))
            on_result = self._request("POST", f"/v1/outlets/{self.config.outlet_id}/on", {})
            if not on_result.success:
                return on_result
            return ProviderOperationResult(
                True,
                "Power cycled",
                {**self._base_metadata(), "power": "on"},
            )

        result = self._request("POST", f"/v1/outlets/{self.config.outlet_id}/{command}", {})
        if not result.success:
            return result

        expected = "on" if command in {"on", "reset", "cycle"} else "off"
        data = result.data or {}
        state = str(data.get("power", expected)).strip().lower()
        if state not in {"on", "off"}:
            state = expected

        messages = {
            "on": "Powered on",
            "off": "Powered off",
            "reset": "Target reset issued",
            "cycle": "Power cycled",
        }
        return ProviderOperationResult(
            True,
            messages[command],
            {**self._base_metadata(), "power": state},
        )

    def health_check(self) -> ProviderOperationResult:
        if not self._is_real():
            return ProviderOperationResult(
                True,
                "Power provider is available",
                {**self._base_metadata(), "power": self._current()},
            )
        status = self._real_status()
        if not status.success:
            return ProviderOperationResult(False, status.message, self._base_metadata())
        return ProviderOperationResult(True, "Power provider is available", status.data)

    def execute(self, operation, params=None):
        if operation in POWER_ALLOWED_COMMANDS:
            try:
                validated_params = self._validated_params(operation, params)
            except ValueError as exc:
                return ProviderOperationResult(False, str(exc))

            if not self._is_real():
                if operation == "status":
                    return ProviderOperationResult(
                        True,
                        "Power status",
                        {"provider_key": self.provider_key, "power": self._current(), "mode": POWER_MODE_SIMULATED},
                    )
                if operation == "on":
                    self._set("on")
                    return ProviderOperationResult(True, "Powered on", {"power": "on", "mode": POWER_MODE_SIMULATED})
                if operation == "off":
                    self._set("off")
                    return ProviderOperationResult(True, "Powered off", {"power": "off", "mode": POWER_MODE_SIMULATED})
                if operation == "reset":
                    self._set("on")
                    return ProviderOperationResult(
                        True,
                        "Target reset issued",
                        {"power": "on", "mode": POWER_MODE_SIMULATED},
                    )
                if operation == "cycle":
                    self._set("off")
                    self._set("on")
                    return ProviderOperationResult(
                        True,
                        "Power cycled",
                        {"power": "on", "mode": POWER_MODE_SIMULATED},
                    )

            if operation == "status":
                return self._real_status()
            if operation == "cycle":
                delay_override = validated_params.get("delay_seconds")
                if delay_override is not None:
                    try:
                        delay = _as_float(
                            delay_override,
                            name="delay_seconds",
                            minimum=0.0,
                            maximum=30.0,
                        )
                    except ValueError as exc:
                        return ProviderOperationResult(False, str(exc))
                else:
                    delay = None
                return self._real_command("cycle", delay_seconds=delay)
            return self._real_command(operation)
        return super().execute(operation, params)
