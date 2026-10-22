from __future__ import annotations

import os
import re
from typing import Any

from app.providers.base import TargetProvider
from app.providers.debugger import DebuggerProvider, build_debugger_provider_config
from app.providers.deployment import DeploymentProvider, build_deployment_provider_config
from app.providers.network import NetworkProvider, build_network_provider_config
from app.providers.power import (
    PowerProvider,
    build_power_provider_config,
)
from app.providers.serial import SerialProvider, SerialProviderConfig, SimulatedSerialProvider

# capability_type -> canonical provider family
CAPABILITY_PROVIDERS: dict[str, str] = {
    "serial": "serial",
    "power": "power",
    "reset": "power",
    "ssh": "network",
    "telnet": "network",
    "ftp": "network",
    "network": "network",
    "jlink": "debugger",
    "deploy": "deploy",
}


def env_prefix(provider_key: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9]+", "_", provider_key).strip("_").upper()
    return f"TARGETHUB_{normalized}"


def _build_serial(provider_key: str, provider_config: dict[str, Any]) -> TargetProvider:
    prefix = env_prefix(provider_key)
    port = os.getenv(f"{prefix}_PORT") or provider_config.get("port")
    if not port:
        # No physical device configured: demonstrate via simulated console.
        return SimulatedSerialProvider(provider_key)

    baudrate = int(os.getenv(f"{prefix}_BAUDRATE", str(provider_config.get("baudrate", 115200))))
    timeout = float(os.getenv(f"{prefix}_TIMEOUT", str(provider_config.get("timeout", 0.2))))
    return SerialProvider(
        SerialProviderConfig(provider_key=provider_key, port=port, baudrate=baudrate, timeout=timeout)
    )


def _build_power(provider_key: str, provider_config: dict[str, Any]) -> TargetProvider:
    parsed = build_power_provider_config(provider_key, provider_config)
    return PowerProvider(parsed)


def _build_network(
    capability_type: str,
    provider_key: str,
    provider_config: dict[str, Any],
) -> TargetProvider:
    parsed = build_network_provider_config(provider_key, capability_type, provider_config)
    return NetworkProvider(parsed)


def _build_debugger(provider_key: str, provider_config: dict[str, Any]) -> TargetProvider:
    parsed = build_debugger_provider_config(provider_key, provider_config)
    return DebuggerProvider(parsed)


def _build_deployment(provider_key: str, provider_config: dict[str, Any]) -> TargetProvider:
    parsed = build_deployment_provider_config(provider_key, provider_config)
    return DeploymentProvider(parsed)


def is_supported(capability_type: str) -> bool:
    return capability_type in CAPABILITY_PROVIDERS


def validate_provider_config(
    capability_type: str,
    provider_key: str | None,
    provider_config: dict[str, Any] | None,
) -> None:
    family = CAPABILITY_PROVIDERS.get(capability_type)
    if family is None:
        raise ValueError(f"Unsupported capability type '{capability_type}'")
    if family == "power":
        build_power_provider_config(provider_key or capability_type, provider_config)
    if family == "network":
        build_network_provider_config(provider_key or capability_type, capability_type, provider_config)
    if family == "debugger":
        build_debugger_provider_config(provider_key or capability_type, provider_config)
    if family == "deploy":
        build_deployment_provider_config(provider_key or capability_type, provider_config)


def build_provider(
    capability_type: str, provider_key: str, provider_config: dict[str, Any] | None = None
) -> TargetProvider:
    """Return a provider instance for the given capability type.

    Serial uses real hardware when configured, otherwise a simulated console.
    Power supports validated real-controller mode plus simulated mode.
    All other providers run in simulated mode so every capability is
    demonstrable without physical hardware.
    """
    provider_config = provider_config or {}
    family = CAPABILITY_PROVIDERS.get(capability_type)
    if family is None:
        raise ValueError(f"Unsupported capability type '{capability_type}'")

    if family == "serial":
        return _build_serial(provider_key, provider_config)
    if family == "power":
        return _build_power(provider_key, provider_config)
    if family == "network":
        return _build_network(capability_type, provider_key, provider_config)
    if family == "debugger":
        return _build_debugger(provider_key, provider_config)
    if family == "deploy":
        return _build_deployment(provider_key, provider_config)

    raise ValueError(f"Unsupported capability type '{capability_type}'")
