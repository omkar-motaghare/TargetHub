from app.core.exceptions import ConflictResource, DuplicateResource, ResourceNotFound
from app.models.target_capability import TargetCapability
from app.providers import registry
from app.repositories.agent_repository import AgentRepository
from app.repositories.target_capability_repository import TargetCapabilityRepository
from app.repositories.target_repository import TargetRepository
from app.services.capability_binding import validate_capability_mapping_inputs


class TargetCapabilityService:
    def __init__(
        self,
        capability_repository: TargetCapabilityRepository,
        target_repository: TargetRepository,
        agent_repository: AgentRepository,
    ):
        self.capability_repository = capability_repository
        self.target_repository = target_repository
        self.agent_repository = agent_repository

    def _validate_mapping(
        self,
        *,
        capability_type: str,
        agent_id: str | None,
        resource_id: str | None,
        enabled: bool,
    ) -> None:
        if bool(agent_id) != bool(resource_id):
            raise ConflictResource("Capability mapping requires both agent_id and resource_id")

        if not agent_id and not resource_id:
            return

        agent = self.agent_repository.get(agent_id)
        if agent is None:
            raise ResourceNotFound("Agent", agent_id)

        resource = self.agent_repository.get_resource(resource_id)
        if resource is None:
            raise ResourceNotFound("Agent resource", resource_id)

        validate_capability_mapping_inputs(
            capability_type,
            agent,
            resource,
            require_agent_enabled=True,
            require_resource_available=enabled,
        )

    def _ensure_target(self, target_id: str):
        target = self.target_repository.get(target_id)
        if target is None:
            raise ResourceNotFound("Target", target_id)
        return target

    def list_capabilities(self, target_id: str):
        self._ensure_target(target_id)
        return self.capability_repository.list_for_target(target_id)

    def get_capability(self, target_id: str, capability_id: str):
        self._ensure_target(target_id)
        capability = self.capability_repository.get(target_id, capability_id)
        if capability is None:
            raise ResourceNotFound("Target capability", capability_id)
        return capability

    def create_capability(self, target_id: str, **kwargs):
        self._ensure_target(target_id)

        if self.capability_repository.get_by_name(target_id, kwargs["name"]):
            raise DuplicateResource("Target capability", kwargs["name"])

        self._validate_mapping(
            capability_type=kwargs["capability_type"],
            agent_id=kwargs.get("agent_id"),
            resource_id=kwargs.get("resource_id"),
            enabled=kwargs.get("enabled", True),
        )
        try:
            registry.validate_provider_config(
                kwargs["capability_type"],
                kwargs.get("provider_key"),
                kwargs.get("provider_config", {}),
            )
        except ValueError as exc:
            raise ConflictResource(str(exc)) from exc

        capability = TargetCapability(target_id=target_id, **kwargs)
        return self.capability_repository.create(capability)

    def update_capability(self, target_id: str, capability_id: str, **kwargs):
        capability = self.get_capability(target_id, capability_id)

        next_capability_type = kwargs.get("capability_type", capability.capability_type)
        next_agent_id = kwargs.get("agent_id", capability.agent_id)
        next_resource_id = kwargs.get("resource_id", capability.resource_id)
        next_enabled = kwargs.get("enabled", capability.enabled)

        self._validate_mapping(
            capability_type=next_capability_type,
            agent_id=next_agent_id,
            resource_id=next_resource_id,
            enabled=next_enabled,
        )
        next_provider_key = kwargs.get("provider_key", capability.provider_key)
        next_provider_config = kwargs.get("provider_config", capability.provider_config)
        try:
            registry.validate_provider_config(
                next_capability_type,
                next_provider_key,
                next_provider_config,
            )
        except ValueError as exc:
            raise ConflictResource(str(exc)) from exc

        for key, value in kwargs.items():
            setattr(capability, key, value)

        return self.capability_repository.update(capability)

    def delete_capability(self, target_id: str, capability_id: str):
        capability = self.get_capability(target_id, capability_id)
        self.capability_repository.delete(capability)
