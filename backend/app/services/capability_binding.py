from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.core.exceptions import ConflictResource
from app.providers import registry
from app.services.agent_service import AGENT_OFFLINE_AFTER_SECONDS


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _resource_type_is_compatible(capability_type: str, resource_type: str) -> bool:
    normalized_capability = capability_type.strip().lower()
    normalized_resource = resource_type.strip().lower()
    family = registry.CAPABILITY_PROVIDERS.get(normalized_capability)
    if family is None:
        return False
    return normalized_resource in {normalized_capability, family}


def validate_capability_mapping_inputs(
    capability_type: str,
    agent,
    resource,
    *,
    require_agent_enabled: bool,
    require_resource_available: bool,
) -> None:
    """Validate static mapping integrity for a target capability configuration."""
    if resource.agent_id != agent.id:
        raise ConflictResource("Selected resource does not belong to selected Agent")

    if require_agent_enabled and not agent.enabled:
        raise ConflictResource("Selected Agent is disabled")

    if require_resource_available and not resource.available:
        raise ConflictResource("Selected resource is unavailable")

    if not _resource_type_is_compatible(capability_type, resource.resource_type):
        raise ConflictResource(
            f"Selected resource type '{resource.resource_type}' is incompatible "
            f"with capability '{capability_type}'"
        )

    if _is_simulated_resource(resource) and not registry.simulation_allowed():
        raise ConflictResource(
            "Selected resource is a simulated Agent device; simulated providers are disabled on this server "
            "(set ALLOW_SIMULATED_PROVIDERS=true for demos)"
        )


def _is_simulated_resource(resource) -> bool:
    metadata = getattr(resource, "resource_metadata", None) or {}
    return bool(metadata.get("simulated")) or str(getattr(resource, "resource_key", "")).startswith("sim://")


def validate_capability_runtime_binding(capability, now: datetime | None = None) -> None:
    """Validate runtime readiness for session creation/execution.

    This check is intentionally strict and enforces that an enabled capability
    is backed by an enabled, credentialed, online Agent and an available,
    compatible resource that belongs to that Agent.
    """
    if not capability.agent_id and not capability.resource_id:
        # Server-hosted capability (e.g. DD power): the hub itself talks to the device.
        try:
            registry.validate_provider_config(
                capability.capability_type,
                capability.provider_key,
                capability.provider_config or {},
                agent_backed=False,
            )
        except ValueError as exc:
            raise ConflictResource(str(exc)) from exc
        return
    if not capability.agent_id or not capability.resource_id:
        raise ConflictResource(
            "Capability is not fully mapped to an Agent resource"
        )

    agent = capability.agent
    if agent is None:
        raise ConflictResource("Configured Agent was not found")
    if not agent.enabled:
        raise ConflictResource("Configured Agent is disabled")
    if not agent.credential_hash or agent.credential_revoked_at is not None:
        raise ConflictResource("Configured Agent credential is missing or revoked")

    resource = capability.resource
    if resource is None:
        raise ConflictResource("Configured Agent resource was not found")
    if resource.agent_id != agent.id:
        raise ConflictResource("Configured resource does not belong to configured Agent")
    if not resource.available:
        raise ConflictResource("Configured Agent resource is unavailable")
    if not _resource_type_is_compatible(capability.capability_type, resource.resource_type):
        raise ConflictResource(
            f"Configured resource type '{resource.resource_type}' is incompatible "
            f"with capability '{capability.capability_type}'"
        )

    now = now or datetime.now(UTC)
    if agent.status != "online":
        raise ConflictResource("Configured Agent is offline")
    if agent.last_seen_at is None:
        raise ConflictResource("Configured Agent has no heartbeat")
    cutoff = now - timedelta(seconds=AGENT_OFFLINE_AFTER_SECONDS)
    if _as_utc(agent.last_seen_at) < cutoff:
        raise ConflictResource("Configured Agent heartbeat is stale")