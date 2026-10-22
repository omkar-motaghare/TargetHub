from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from app.providers.base import ProviderOperationResult, TargetProvider

DEPLOYMENT_MODE_SIMULATED = "simulated"
DEPLOYMENT_MODE_REAL = "real"
DEPLOYMENT_ALLOWED_MODES = {DEPLOYMENT_MODE_SIMULATED, DEPLOYMENT_MODE_REAL}
DEPLOYMENT_ALLOWED_AUTH_TYPES = {"none", "bearer"}
ENV_NAME_PATTERN = re.compile(r"^[A-Z_][A-Z0-9_]{0,127}$")
TARGET_ID_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{1,64}$")
ARTIFACT_PATTERN = re.compile(r"^[A-Za-z0-9._/-]{1,255}$")


def _as_float(value: object, *, name: str, minimum: float, maximum: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"deployment provider '{name}' must be a number") from exc
    if parsed < minimum or parsed > maximum:
        raise ValueError(f"deployment provider '{name}' must be between {minimum} and {maximum}")
    return parsed


def _as_mode(value: object) -> str:
    candidate = str(value or DEPLOYMENT_MODE_SIMULATED).strip().lower()
    if candidate not in DEPLOYMENT_ALLOWED_MODES:
        allowed = ", ".join(sorted(DEPLOYMENT_ALLOWED_MODES))
        raise ValueError(f"deployment provider mode must be one of: {allowed}")
    return candidate


def _as_auth_type(value: object) -> str:
    candidate = str(value or "none").strip().lower()
    if candidate not in DEPLOYMENT_ALLOWED_AUTH_TYPES:
        allowed = ", ".join(sorted(DEPLOYMENT_ALLOWED_AUTH_TYPES))
        raise ValueError(f"deployment provider auth_type must be one of: {allowed}")
    return candidate


def _as_env_name(value: object, *, name: str) -> str:
    candidate = str(value or "").strip()
    if not ENV_NAME_PATTERN.fullmatch(candidate):
        raise ValueError(f"deployment provider '{name}' must be a valid environment variable name")
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


def _sanitize_artifact_name(value: object) -> str:
    artifact = str(value or "").strip()
    if not artifact:
        raise ValueError("artifact is required")
    if not ARTIFACT_PATTERN.fullmatch(artifact):
        raise ValueError("artifact contains unsupported characters")
    if artifact.startswith("/") or ".." in artifact:
        raise ValueError("artifact path must be relative and must not contain '..'")
    return artifact


@dataclass(slots=True)
class DeploymentProviderConfig:
    provider_key: str
    provider_config: dict[str, Any] = field(default_factory=dict)
    mode: str = DEPLOYMENT_MODE_SIMULATED
    controller_url: str | None = None
    target_id: str | None = None
    timeout_seconds: float = 20.0
    auth_type: str = "none"
    bearer_token_env: str | None = None
    tls_skip_verify: bool = False


def build_deployment_provider_config(
    provider_key: str,
    provider_config: dict[str, Any] | None,
) -> DeploymentProviderConfig:
    cfg = provider_config or {}
    mode = _as_mode(cfg.get("mode"))
    timeout_seconds = _as_float(
        cfg.get("timeout_seconds", 20.0),
        name="timeout_seconds",
        minimum=0.5,
        maximum=300.0,
    )

    if mode == DEPLOYMENT_MODE_SIMULATED:
        return DeploymentProviderConfig(
            provider_key=provider_key,
            provider_config=cfg,
            mode=mode,
            timeout_seconds=timeout_seconds,
        )

    controller_url = str(cfg.get("controller_url", "")).strip()
    if not controller_url:
        raise ValueError("deployment provider real mode requires 'controller_url'")
    parsed = urllib.parse.urlparse(controller_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("deployment provider 'controller_url' must be a valid http(s) URL")

    target_id = str(cfg.get("target_id", "")).strip()
    if not TARGET_ID_PATTERN.fullmatch(target_id):
        raise ValueError("deployment provider 'target_id' must match ^[A-Za-z0-9._:-]{1,64}$")

    auth_type = _as_auth_type(cfg.get("auth_type"))
    bearer_token_env = None
    if auth_type == "bearer":
        bearer_token_env = _as_env_name(cfg.get("bearer_token_env"), name="bearer_token_env")

    tls_skip_verify = _as_bool(cfg.get("tls_skip_verify"), default=False)

    return DeploymentProviderConfig(
        provider_key=provider_key,
        provider_config=cfg,
        mode=mode,
        controller_url=controller_url.rstrip("/"),
        target_id=target_id,
        timeout_seconds=timeout_seconds,
        auth_type=auth_type,
        bearer_token_env=bearer_token_env,
        tls_skip_verify=tls_skip_verify,
    )


class DeploymentProvider(TargetProvider):
    """Firmware deployment provider (flash / status).

    Simulated by default. Real mode sends deployment operations to a
    controller API:

    - `POST {controller_url}/v1/deployments/{target_id}/deploy`
    - `GET  {controller_url}/v1/deployments/{target_id}/status`
    """

    capability_type = "deploy"

    _last: dict[str, dict[str, Any]] = {}

    def __init__(self, config: DeploymentProviderConfig) -> None:
        self.config = config
        self.provider_key = config.provider_key

    def operations(self) -> list[str]:
        return ["health", "deploy", "status"]

    def _is_real(self) -> bool:
        return self.config.mode == DEPLOYMENT_MODE_REAL

    def _base_metadata(self) -> dict[str, Any]:
        payload = {
            "provider_key": self.provider_key,
            "mode": self.config.mode,
        }
        if self._is_real():
            payload["target_id"] = self.config.target_id
        return payload

    def _build_headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if not self._is_real() or self.config.auth_type == "none":
            return headers
        if self.config.auth_type == "bearer":
            assert self.config.bearer_token_env is not None
            token = os.getenv(self.config.bearer_token_env, "")
            if not token:
                raise ValueError(
                    f"Deployment controller token is missing in env '{self.config.bearer_token_env}'"
                )
            headers["Authorization"] = f"Bearer {token}"
            return headers
        raise ValueError(f"Unsupported deployment auth_type '{self.config.auth_type}'")

    def _request(self, method: str, path: str, body: dict[str, Any] | None = None) -> ProviderOperationResult:
        assert self.config.controller_url is not None
        if ".." in path:
            return ProviderOperationResult(False, "Unsafe deployment-controller path rejected")
        url = f"{self.config.controller_url}{path}"
        if self.config.tls_skip_verify and url.lower().startswith("https://"):
            return ProviderOperationResult(
                False,
                "deployment provider tls_skip_verify is not permitted",
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
                    return ProviderOperationResult(False, "Deployment controller returned an invalid response")
                return ProviderOperationResult(True, "Deployment controller request succeeded", data)
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            return ProviderOperationResult(False, f"Deployment controller rejected request ({exc.code}): {detail}")
        except urllib.error.URLError as exc:
            return ProviderOperationResult(False, f"Deployment controller is unreachable: {exc.reason}")
        except TimeoutError:
            return ProviderOperationResult(False, "Deployment controller request timed out")
        except json.JSONDecodeError:
            return ProviderOperationResult(False, "Deployment controller returned malformed JSON")
        except ValueError as exc:
            return ProviderOperationResult(False, str(exc))

    @staticmethod
    def _validated_bytes(value: object) -> int:
        try:
            parsed = int(value)
        except (TypeError, ValueError) as exc:
            raise ValueError("bytes must be an integer") from exc
        if parsed < 1 or parsed > 1_000_000_000:
            raise ValueError("bytes must be between 1 and 1000000000")
        return parsed

    def _real_status(self) -> ProviderOperationResult:
        assert self.config.target_id is not None
        status = self._request("GET", f"/v1/deployments/{self.config.target_id}/status")
        if not status.success:
            return status
        data = status.data or {}
        if "status" not in data:
            data["status"] = "unknown"
        return ProviderOperationResult(True, "Last deployment", {**self._base_metadata(), **data})

    def _real_deploy(self, artifact: str, payload_size: int) -> ProviderOperationResult:
        assert self.config.target_id is not None
        result = self._request(
            "POST",
            f"/v1/deployments/{self.config.target_id}/deploy",
            {"artifact": artifact, "bytes": payload_size},
        )
        if not result.success:
            return result
        data = result.data or {}
        data.setdefault("artifact", artifact)
        data.setdefault("bytes", payload_size)
        data.setdefault("status", "success")
        return ProviderOperationResult(True, f"Deployed '{artifact}'", {**self._base_metadata(), **data})

    def _simulated_deploy(self, artifact: str, payload_size: int) -> ProviderOperationResult:
        record = {
            "artifact": artifact,
            "bytes": payload_size,
            "status": "success",
            "deployed_at": datetime.now(UTC).isoformat(),
        }
        self._last[self.provider_key] = record
        return ProviderOperationResult(True, f"Deployed '{artifact}'", dict(record))

    def health_check(self) -> ProviderOperationResult:
        if self._is_real():
            status = self._real_status()
            if not status.success:
                return ProviderOperationResult(False, status.message, self._base_metadata())
            return ProviderOperationResult(True, "Deployment provider is available", status.data)
        return ProviderOperationResult(
            True, "Deployment provider is available", {"provider_key": self.provider_key, "mode": "simulated"}
        )

    def execute(self, operation, params=None):
        params = params or {}
        if operation == "deploy":
            try:
                artifact = _sanitize_artifact_name(params.get("artifact", "firmware.bin"))
                payload_size = self._validated_bytes(params.get("bytes", 262144))
            except ValueError as exc:
                return ProviderOperationResult(False, str(exc))

            if self._is_real():
                return self._real_deploy(artifact, payload_size)
            return self._simulated_deploy(artifact, payload_size)
        if operation == "status":
            if self._is_real():
                return self._real_status()

            record = self._last.get(self.provider_key)
            if not record:
                return ProviderOperationResult(True, "No deployment yet", {"status": "none"})
            return ProviderOperationResult(True, "Last deployment", dict(record))
        return super().execute(operation, params)
