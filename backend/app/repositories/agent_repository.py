from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.models.agent import Agent, AgentEnrollment, AgentResource
from app.models.target_capability import TargetCapability


class AgentRepository:
    def __init__(self, db: Session):
        self.db = db

    def list(self):
        return self.db.query(Agent).order_by(Agent.name).all()

    def get(self, agent_id: str):
        return self.db.query(Agent).filter(Agent.id == agent_id).first()

    def get_resource(self, resource_id: str):
        return self.db.query(AgentResource).filter(AgentResource.id == resource_id).first()

    def get_by_name(self, name: str):
        return self.db.query(Agent).filter(Agent.name == name).first()

    def get_by_credential_hash(self, credential_hash: str):
        return self.db.query(Agent).filter(Agent.credential_hash == credential_hash).first()

    def get_enrollment_by_token_hash(self, token_hash: str):
        return self.db.query(AgentEnrollment).filter(AgentEnrollment.token_hash == token_hash).first()

    def list_enrollments(self):
        return self.db.query(AgentEnrollment).order_by(AgentEnrollment.created_at.desc()).all()

    def create(self, agent: Agent):
        self.db.add(agent)
        self.db.commit()
        self.db.refresh(agent)
        return agent

    def create_enrollment(self, enrollment: AgentEnrollment):
        self.db.add(enrollment)
        self.db.commit()
        self.db.refresh(enrollment)
        return enrollment

    def save(self, agent: Agent):
        self.db.commit()
        self.db.refresh(agent)
        return agent

    def save_enrollment(self, enrollment: AgentEnrollment):
        self.db.commit()
        self.db.refresh(enrollment)
        return enrollment

    def replace_resources(self, agent: Agent, resources: list[AgentResource]):
        agent.resources.clear()
        agent.resources.extend(resources)
        self.db.commit()
        self.db.refresh(agent)
        return agent

    def disable_capabilities_for_agent(self, agent_id: str) -> int:
        rows = (
            self.db.query(TargetCapability)
            .filter(
                TargetCapability.agent_id == agent_id,
                TargetCapability.enabled.is_(True),
            )
            .all()
        )
        for capability in rows:
            capability.enabled = False
        if rows:
            self.db.commit()
        return len(rows)

    def delete_enrollment(self, enrollment: AgentEnrollment):
        self.db.delete(enrollment)
        self.db.commit()

    def utc_now(self) -> datetime:
        return datetime.now(UTC)
