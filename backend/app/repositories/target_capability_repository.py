from sqlalchemy.orm import Session

from app.models.target_capability import TargetCapability


class TargetCapabilityRepository:
    def __init__(self, db: Session):
        self.db = db

    def list_for_target(self, target_id: str):
        return (
            self.db.query(TargetCapability)
            .filter(TargetCapability.target_id == target_id)
            .order_by(TargetCapability.name)
            .all()
        )

    def get(self, target_id: str, capability_id: str):
        return (
            self.db.query(TargetCapability)
            .filter(
                TargetCapability.id == capability_id,
                TargetCapability.target_id == target_id,
            )
            .first()
        )

    def get_by_name(self, target_id: str, name: str):
        return (
            self.db.query(TargetCapability)
            .filter(
                TargetCapability.target_id == target_id,
                TargetCapability.name == name,
            )
            .first()
        )

    def create(self, capability: TargetCapability):
        self.db.add(capability)
        self.db.commit()
        self.db.refresh(capability)
        return capability

    def update(self, capability: TargetCapability):
        self.db.commit()
        self.db.refresh(capability)
        return capability

    def delete(self, capability: TargetCapability):
        self.db.delete(capability)
        self.db.commit()
