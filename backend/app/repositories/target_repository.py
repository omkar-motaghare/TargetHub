from sqlalchemy.orm import Session, selectinload

from app.models.target import Target


class TargetRepository:
    def __init__(self, db: Session):
        self.db = db

    def list(self, tag: str | None = None, lab: str | None = None):
        query = self.db.query(Target).options(selectinload(Target.capabilities))
        if lab:
            query = query.filter(Target.lab_name == lab)
        targets = query.order_by(Target.name).all()
        if tag:
            # JSON containment differs per database; tags are small, filter in Python.
            targets = [target for target in targets if tag in (target.tags or [])]
        return targets

    def get(self, target_id: str):
        return (
            self.db.query(Target)
            .options(selectinload(Target.capabilities))
            .filter(Target.id == target_id)
            .first()
        )

    def get_by_name(self, name: str):
        return self.db.query(Target).filter(Target.name == name).first()

    def create(self, target: Target):
        self.db.add(target)
        self.db.commit()
        self.db.refresh(target)
        return target

    def update(self, target: Target):
        self.db.commit()
        self.db.refresh(target)
        return target

    def delete(self, target: Target):
        self.db.delete(target)
        self.db.commit()
