from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Any

from app.providers.base import ProviderOperationResult, TargetProvider

DEBUGGER_MODE_SIMULATED = "simulated"
DEBUGGER_MODE_REAL = "real"
DEBUGGER_ALLOWED_MODES = {DEBUGGER_MODE_SIMULATED, DEBUGGER_MODE_REAL}
DEBUGGER_ALLOWED_AUTH_TYPES = {"none", "bearer"}
ENV_NAME_PATTERN = re.compile(r"^[A-Z_][A-Z0-9_]{0,127}$")
PROBE_ID_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{1,64}$")


def _as_float(value: object, *, name: str, minimum: float, maximum: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"debugger provider '{name}' must be a number") from exc
    if parsed < minimum or parsed > maximum:
        raise ValueError(f"debugger provider '{name}' must be between {minimum} and {maximum}")
    return parsed


def _as_mode(value: object) -> str:
    candidate = str(value or DEBUGGER_MODE_SIMULATED).strip().lower()
    if candidate not in DEBUGGER_ALLOWED_MODES:
        allowed = ", ".join(sorted(DEBUGGER_ALLOWED_MODES))
        raise ValueError(f"debugger provider mode must be one of: {allowed}")
    return candidate


def _as_auth_type(value: object) -> str:
    candidate = str(value or "none").strip().lower()
    if candidate not in DEBUGGER_ALLOWED_AUTH_TYPES:
        allowed = ", ".join(sorted(DEBUGGER_ALLOWED_AUTH_TYPES))
        raise ValueError(f"debugger provider auth_type must be one of: {allowed}")
    return candidate


def _as_env_name(value: object, *, name: str) -> str:
    candidate = str(value or "").strip()
    if not ENV_NAME_PATTERN.fullmatch(candidate):
        raise ValueError(f"debugger provider '{name}' must be a valid environment variable name")
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
class DebuggerProviderConfig:
    provider_key: str
    provider_config: dict[str, Any] = field(default_factory=dict)
    mode: str = DEBUGGER_MODE_SIMULATED
    controller_url: str | None = None
    probe_id: str | None = None
    timeout_seconds: float = 8.0
    auth_type: str = "none"
    bearer_token_env: str | None = None
    tls_skip_verify: bool = False


def build_debugger_provider_config(
    provider_key: str,
    provider_config: dict[str, Any] | None,
) -> DebuggerProviderConfig:
    cfg = provider_config or {}
    mode = _as_mode(cfg.get("mode"))
    timeout_seconds = _as_float(
        cfg.get("timeout_seconds", 8.0),
        name="timeout_seconds",
        minimum=0.2,
        maximum=120.0,
    )

    if mode == DEBUGGER_MODE_SIMULATED:
        return DebuggerProviderConfig(
            provider_key=provider_key,
            provider_config=cfg,
            mode=mode,
            timeout_seconds=timeout_seconds,
        )

    controller_url = str(cfg.get("controller_url", "")).strip()
    if not controller_url:
        raise ValueError("debugger provider real mode requires 'controller_url'")
    parsed = urllib.parse.urlparse(controller_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("debugger provider 'controller_url' must be a valid http(s) URL")

    probe_id = str(cfg.get("probe_id", "")).strip()
    if not PROBE_ID_PATTERN.fullmatch(probe_id):
        raise ValueError("debugger provider 'probe_id' must match ^[A-Za-z0-9._:-]{1,64}$")

    auth_type = _as_auth_type(cfg.get("auth_type"))
    bearer_token_env = None
    if auth_type == "bearer":
        bearer_token_env = _as_env_name(cfg.get("bearer_token_env"), name="bearer_token_env")

    tls_skip_verify = _as_bool(cfg.get("tls_skip_verify"), default=False)

    return DebuggerProviderConfig(
        provider_key=provider_key,
        provider_config=cfg,
        mode=mode,
        controller_url=controller_url.rstrip("/"),
        probe_id=probe_id,
        timeout_seconds=timeout_seconds,
        auth_type=auth_type,
        bearer_token_env=bearer_token_env,
        tls_skip_verify=tls_skip_verify,
    )


class DebuggerProvider(TargetProvider):
    """Debugger provider (J-Link / Cortex-Debug style) with attach/halt/resume/reset.

    Simulated by default. Real mode sends actions to a debugger-controller API:

    - `GET  {controller_url}/v1/probes/{probe_id}/status`
    - `POST {controller_url}/v1/probes/{probe_id}/attach|detach|halt|resume|reset`
    """

    capability_type = "jlink"

    _state: dict[str, dict[str, Any]] = {}

    def __init__(self, config: DebuggerProviderConfig) -> None:
        self.config = config
        self.provider_key = config.provider_key

    def operations(self) -> list[str]:
        return ["health", "status", "attach", "detach", "halt", "resume", "reset"]

    def _is_real(self) -> bool:
        return self.config.mode == DEBUGGER_MODE_REAL

    def _base_metadata(self) -> dict[str, Any]:
        payload = {
            "provider_key": self.provider_key,
            "mode": self.config.mode,
        }
        if self._is_real():
            payload["probe_id"] = self.config.probe_id
        return payload

    def _dev(self) -> dict[str, Any]:
        return self._state.setdefault(
            self.provider_key, {"attached": False, "core": "running"}
        )

    def _build_headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if not self._is_real() or self.config.auth_type == "none":
            return headers
        if self.config.auth_type == "bearer":
            assert self.config.bearer_token_env is not None
            token = os.getenv(self.config.bearer_token_env, "")
            if not token:
                raise ValueError(
                    f"Debugger controller token is missing in env '{self.config.bearer_token_env}'"
                )
            headers["Authorization"] = f"Bearer {token}"
            return headers
        raise ValueError(f"Unsupported debugger auth_type '{self.config.auth_type}'")

    def _request(self, method: str, path: str, body: dict[str, Any] | None = None) -> ProviderOperationResult:
        assert self.config.controller_url is not None
        if ".." in path:
            return ProviderOperationResult(False, "Unsafe debugger-controller path rejected")
        url = f"{self.config.controller_url}{path}"
        if self.config.tls_skip_verify and url.lower().startswith("https://"):
            return ProviderOperationResult(
                False,
                "debugger provider tls_skip_verify is not permitted",
            )
        data = None if body is None else json.dumps(body).encode("utf-8")
        try:
            request = urllib.request.Request(
                url,
                data=data,
                headers=self._build_headers(),
                method=method,
            )
            with urllib.request.urlopen(
                request,
                timeout=self.config.timeout_seconds,
            ) as response:
                payload = response.read().decode("utf-8")
                data = json.loads(payload) if payload else {}
                if not isinstance(data, dict):
                    return ProviderOperationResult(False, "Debugger controller returned an invalid response")
                return ProviderOperationResult(True, "Debugger controller request succeeded", data)
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            return ProviderOperationResult(False, f"Debugger controller rejected request ({exc.code}): {detail}")
        except urllib.error.URLError as exc:
            return ProviderOperationResult(False, f"Debugger controller is unreachable: {exc.reason}")
        except TimeoutError:
            return ProviderOperationResult(False, "Debugger controller request timed out")
        except json.JSONDecodeError:
            return ProviderOperationResult(False, "Debugger controller returned malformed JSON")
        except ValueError as exc:
            return ProviderOperationResult(False, str(exc))

    def _real_action(self, operation: str) -> ProviderOperationResult:
        assert self.config.probe_id is not None
        if operation == "status":
            result = self._request("GET", f"/v1/probes/{self.config.probe_id}/status")
        else:
            result = self._request("POST", f"/v1/probes/{self.config.probe_id}/{operation}", {})
        if not result.success:
            return result
        data = result.data or {}
        return ProviderOperationResult(True, f"Debugger {operation} completed", {**self._base_metadata(), **data})

    def health_check(self) -> ProviderOperationResult:
        if self._is_real():
            status = self._real_action("status")
            if not status.success:
                return ProviderOperationResult(False, status.message, self._base_metadata())
            return ProviderOperationResult(True, "Debugger provider is available", status.data)
        return ProviderOperationResult(
            True, "Debugger provider is available", {**self._base_metadata(), **self._dev()}
        )

    def execute(self, operation, params=None):
        if self._is_real() and operation in {"status", "attach", "detach", "halt", "resume", "reset"}:
            return self._real_action(operation)

        dev = self._dev()
        if operation == "status":
            return ProviderOperationResult(True, "Debugger status", dict(dev))
        if operation == "attach":
            dev["attached"] = True
            return ProviderOperationResult(True, "Debug probe attached", dict(dev))
        if operation == "detach":
            dev["attached"] = False
            return ProviderOperationResult(True, "Debug probe detached", dict(dev))
        if operation in {"halt", "resume", "reset"}:
            if not dev["attached"]:
                return ProviderOperationResult(False, "Attach the debugger before issuing core operations")
            if operation == "halt":
                dev["core"] = "halted"
                return ProviderOperationResult(True, "Core halted", dict(dev))
            if operation == "resume":
                dev["core"] = "running"
                return ProviderOperationResult(True, "Core resumed", dict(dev))
            dev["core"] = "running"
            return ProviderOperationResult(True, "Core reset", dict(dev))
        return super().execute(operation, params)
