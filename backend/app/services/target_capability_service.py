from app.core.exceptions import DuplicateResource, ResourceNotFound
from app.models.target_capability import TargetCapability
from app.repositories.target_capability_repository import TargetCapabilityRepository
from app.repositories.target_repository import TargetRepository


class TargetCapabilityService:
    def __init__(
        self,
        capability_repository: TargetCapabilityRepository,
        target_repository: TargetRepository,
    ):
        self.capability_repository = capability_repository
        self.target_repository = target_repository

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

        capability = TargetCapability(target_id=target_id, **kwargs)
        return self.capability_repository.create(capability)

    def update_capability(self, target_id: str, capability_id: str, **kwargs):
        capability = self.get_capability(target_id, capability_id)

        for key, value in kwargs.items():
            setattr(capability, key, value)

        return self.capability_repository.update(capability)

    def delete_capability(self, target_id: str, capability_id: str):
        capability = self.get_capability(target_id, capability_id)
        self.capability_repository.delete(capability)
