from app.core.exceptions import ConflictResource, DuplicateResource, ResourceNotFound
from app.models.target import Target
from app.models.target_capability import TargetCapability
from app.providers import registry
from app.repositories.agent_repository import AgentRepository
from app.repositories.target_repository import TargetRepository
from app.services.capability_binding import validate_capability_mapping_inputs


class TargetService:
    def __init__(self, repository: TargetRepository, agent_repository: AgentRepository):
        self.repository = repository
        self.agent_repository = agent_repository

    def _validate_capability_mapping(self, capability: dict):
        agent_id = capability.get("agent_id")
        resource_id = capability.get("resource_id")
        enabled = capability.get("enabled", True)

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
            capability["capability_type"],
            agent,
            resource,
            require_agent_enabled=True,
            require_resource_available=enabled,
        )

    @staticmethod
    def _validate_provider_config(capability: dict) -> None:
        try:
            registry.validate_provider_config(
                capability["capability_type"],
                capability.get("provider_key"),
                capability.get("provider_config", {}),
            )
        except ValueError as exc:
            raise ConflictResource(str(exc)) from exc

    def list_targets(self):
        return self.repository.list()

    def get_target(self, target_id: str):
        target = self.repository.get(target_id)

        if target is None:
            raise ResourceNotFound("Target", target_id)

        return target

    def create_target(self, **kwargs):
        capabilities = kwargs.pop("capabilities", [])

        existing = self.repository.get_by_name(kwargs["name"])
        if existing:
            raise DuplicateResource("Target", kwargs["name"])

        target = Target(**kwargs)
        for capability in capabilities:
            self._validate_capability_mapping(capability)
            self._validate_provider_config(capability)
        target.capabilities = [
            TargetCapability(**capability) for capability in capabilities
        ]
        return self.repository.create(target)

    def update_target(self, target_id: str, **kwargs):
        target = self.get_target(target_id)

        for key, value in kwargs.items():
            setattr(target, key, value)

        return self.repository.update(target)

    def delete_target(self, target_id: str):
        target = self.get_target(target_id)
        self.repository.delete(target)
