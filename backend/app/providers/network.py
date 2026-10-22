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

NETWORK_MODE_SIMULATED = "simulated"
NETWORK_MODE_REAL = "real"
NETWORK_ALLOWED_MODES = {NETWORK_MODE_SIMULATED, NETWORK_MODE_REAL}
NETWORK_ALLOWED_AUTH_TYPES = {"none", "bearer"}
ENV_NAME_PATTERN = re.compile(r"^[A-Z_][A-Z0-9_]{0,127}$")
CHANNEL_ID_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{1,64}$")
COMMAND_PATTERN = re.compile(r"^[A-Za-z0-9._:/=@,+-][A-Za-z0-9._:/=@,+ -]{0,127}$")


def _as_float(value: object, *, name: str, minimum: float, maximum: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"network provider '{name}' must be a number") from exc
    if parsed < minimum or parsed > maximum:
        raise ValueError(f"network provider '{name}' must be between {minimum} and {maximum}")
    return parsed


def _as_mode(value: object) -> str:
    candidate = str(value or NETWORK_MODE_SIMULATED).strip().lower()
    if candidate not in NETWORK_ALLOWED_MODES:
        allowed = ", ".join(sorted(NETWORK_ALLOWED_MODES))
        raise ValueError(f"network provider mode must be one of: {allowed}")
    return candidate


def _as_auth_type(value: object) -> str:
    candidate = str(value or "none").strip().lower()
    if candidate not in NETWORK_ALLOWED_AUTH_TYPES:
        allowed = ", ".join(sorted(NETWORK_ALLOWED_AUTH_TYPES))
        raise ValueError(f"network provider auth_type must be one of: {allowed}")
    return candidate


def _as_env_name(value: object, *, name: str) -> str:
    candidate = str(value or "").strip()
    if not ENV_NAME_PATTERN.fullmatch(candidate):
        raise ValueError(f"network provider '{name}' must be a valid environment variable name")
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


def _as_allowed_commands(value: object) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError("network provider 'allowed_commands' must be a list of strings")
    commands: list[str] = []
    for item in value:
        command = str(item).strip()
        if not command:
            continue
        if not COMMAND_PATTERN.fullmatch(command):
            raise ValueError("network provider allowed command contains unsafe characters")
        commands.append(command)
    return commands


@dataclass(slots=True)
class NetworkProviderConfig:
    provider_key: str
    capability_type: str = "ssh"
    provider_config: dict[str, Any] = field(default_factory=dict)
    mode: str = NETWORK_MODE_SIMULATED
    controller_url: str | None = None
    channel_id: str | None = None
    timeout_seconds: float = 5.0
    auth_type: str = "none"
    bearer_token_env: str | None = None
    tls_skip_verify: bool = False
    allowed_commands: list[str] = field(default_factory=list)


def build_network_provider_config(
    provider_key: str,
    capability_type: str,
    provider_config: dict[str, Any] | None,
) -> NetworkProviderConfig:
    cfg = provider_config or {}
    mode = _as_mode(cfg.get("mode"))
    timeout_seconds = _as_float(
        cfg.get("timeout_seconds", 5.0),
        name="timeout_seconds",
        minimum=0.2,
        maximum=60.0,
    )

    if mode == NETWORK_MODE_SIMULATED:
        return NetworkProviderConfig(
            provider_key=provider_key,
            capability_type=capability_type,
            provider_config=cfg,
            mode=mode,
            timeout_seconds=timeout_seconds,
        )

    controller_url = str(cfg.get("controller_url", "")).strip()
    if not controller_url:
        raise ValueError("network provider real mode requires 'controller_url'")
    parsed = urllib.parse.urlparse(controller_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("network provider 'controller_url' must be a valid http(s) URL")

    channel_id = str(cfg.get("channel_id", "")).strip()
    if not CHANNEL_ID_PATTERN.fullmatch(channel_id):
        raise ValueError("network provider 'channel_id' must match ^[A-Za-z0-9._:-]{1,64}$")

    auth_type = _as_auth_type(cfg.get("auth_type"))
    bearer_token_env = None
    if auth_type == "bearer":
        bearer_token_env = _as_env_name(cfg.get("bearer_token_env"), name="bearer_token_env")

    tls_skip_verify = _as_bool(cfg.get("tls_skip_verify"), default=False)
    allowed_commands = _as_allowed_commands(cfg.get("allowed_commands"))

    return NetworkProviderConfig(
        provider_key=provider_key,
        capability_type=capability_type,
        provider_config=cfg,
        mode=mode,
        controller_url=controller_url.rstrip("/"),
        channel_id=channel_id,
        timeout_seconds=timeout_seconds,
        auth_type=auth_type,
        bearer_token_env=bearer_token_env,
        tls_skip_verify=tls_skip_verify,
        allowed_commands=allowed_commands,
    )


class NetworkProvider(TargetProvider):
    """Network access provider for ssh / telnet / ftp / generic network.

    Simulated by default. Real mode sends authenticated requests to a
    controller API:

    - `GET  {controller_url}/v1/channels/{channel_id}/info`
    - `POST {controller_url}/v1/channels/{channel_id}/exec`
    """

    def __init__(self, config: NetworkProviderConfig) -> None:
        self.config = config
        self.provider_key = config.provider_key
        self.capability_type = config.capability_type

    def operations(self) -> list[str]:
        return ["health", "info", "exec"]

    def _is_real(self) -> bool:
        return self.config.mode == NETWORK_MODE_REAL

    def _base_metadata(self) -> dict[str, Any]:
        payload = {
            "provider_key": self.provider_key,
            "protocol": self.capability_type,
            "mode": self.config.mode,
        }
        if self._is_real():
            payload["channel_id"] = self.config.channel_id
        return payload

    def _connection_info(self) -> dict[str, Any]:
        cfg = self.config.provider_config or {}
        default_port = {"ssh": 22, "telnet": 23, "ftp": 21}.get(self.capability_type, 0)
        return {
            **self._base_metadata(),
            "host": cfg.get("host", "127.0.0.1"),
            "port": cfg.get("port", default_port),
            "username": cfg.get("username", "developer"),
        }

    def _build_headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if not self._is_real() or self.config.auth_type == "none":
            return headers
        if self.config.auth_type == "bearer":
            assert self.config.bearer_token_env is not None
            token = os.getenv(self.config.bearer_token_env, "")
            if not token:
                raise ValueError(
                    f"Network controller token is missing in env '{self.config.bearer_token_env}'"
                )
            headers["Authorization"] = f"Bearer {token}"
            return headers
        raise ValueError(f"Unsupported network auth_type '{self.config.auth_type}'")

    def _request(
        self,
        method: str,
        path: str,
        body: dict[str, Any] | None = None,
    ) -> ProviderOperationResult:
        assert self.config.controller_url is not None
        if ".." in path:
            return ProviderOperationResult(False, "Unsafe network-controller path rejected")
        url = f"{self.config.controller_url}{path}"
        if self.config.tls_skip_verify and url.lower().startswith("https://"):
            return ProviderOperationResult(
                False,
                "network provider tls_skip_verify is not permitted",
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
                    return ProviderOperationResult(False, "Network controller returned an invalid response")
                return ProviderOperationResult(True, "Network controller request succeeded", data)
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            return ProviderOperationResult(False, f"Network controller rejected request ({exc.code}): {detail}")
        except urllib.error.URLError as exc:
            return ProviderOperationResult(False, f"Network controller is unreachable: {exc.reason}")
        except TimeoutError:
            return ProviderOperationResult(False, "Network controller request timed out")
        except json.JSONDecodeError:
            return ProviderOperationResult(False, "Network controller returned malformed JSON")
        except ValueError as exc:
            return ProviderOperationResult(False, str(exc))

    def _sanitize_command(self, params: dict[str, Any]) -> str:
        command = str(params.get("command", "")).strip()
        if not command:
            raise ValueError("command is required")
        if not COMMAND_PATTERN.fullmatch(command):
            raise ValueError("command contains unsupported characters")
        if self._is_real() and self.config.allowed_commands and command not in self.config.allowed_commands:
            raise ValueError("command is not in network allowed_commands")
        return command

    def _real_info(self) -> ProviderOperationResult:
        assert self.config.channel_id is not None
        info = self._request("GET", f"/v1/channels/{self.config.channel_id}/info")
        if not info.success:
            return info
        return ProviderOperationResult(True, "Connection info", {**self._base_metadata(), **(info.data or {})})

    def _real_exec(self, command: str) -> ProviderOperationResult:
        assert self.config.channel_id is not None
        result = self._request(
            "POST",
            f"/v1/channels/{self.config.channel_id}/exec",
            {"command": command, "protocol": self.capability_type},
        )
        if not result.success:
            return result
        data = result.data or {}
        if "exit_code" not in data:
            data["exit_code"] = 0
        data["command"] = command
        return ProviderOperationResult(True, "Command executed", {**self._base_metadata(), **data})

    def _simulated_exec(self, command: str) -> ProviderOperationResult:
        output = f"$ {command}\n[simulated:{self.capability_type}] ok"
        return ProviderOperationResult(
            True,
            "Command executed",
            {"command": command, "output": output, "exit_code": 0},
        )

    def health_check(self) -> ProviderOperationResult:
        if self._is_real():
            info = self._real_info()
            if not info.success:
                return ProviderOperationResult(False, info.message, self._base_metadata())
            return ProviderOperationResult(True, f"{self.capability_type} provider is available", info.data)
        return ProviderOperationResult(
            True, f"{self.capability_type} provider is available", self._connection_info()
        )

    def execute(self, operation, params=None):
        params = params or {}
        if operation == "info":
            if self._is_real():
                return self._real_info()
            return ProviderOperationResult(True, "Connection info", self._connection_info())
        if operation == "exec":
            try:
                command = self._sanitize_command(params)
            except ValueError as exc:
                return ProviderOperationResult(False, str(exc))

            if self._is_real():
                return self._real_exec(command)
            return self._simulated_exec(command)
        return super().execute(operation, params)
