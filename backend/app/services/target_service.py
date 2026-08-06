from app.core.exceptions import DuplicateResource, ResourceNotFound
from app.models.target import Target
from app.repositories.target_repository import TargetRepository


class TargetService:
    def __init__(self, repository: TargetRepository):
        self.repository = repository

    def list_targets(self):
        return self.repository.list()

    def get_target(self, target_id: str):
        target = self.repository.get(target_id)

        if target is None:
            raise ResourceNotFound("Target", target_id)

        return target

    def create_target(self, **kwargs):
        existing = self.repository.get_by_name(kwargs["name"])

        if existing:
            raise DuplicateResource("Target", kwargs["name"])

        return self.repository.create(Target(**kwargs))

    def update_target(self, target_id: str, **kwargs):
        target = self.get_target(target_id)

        for key, value in kwargs.items():
            setattr(target, key, value)

        return self.repository.update(target)

    def delete_target(self, target_id: str):
        target = self.get_target(target_id)
        self.repository.delete(target)
