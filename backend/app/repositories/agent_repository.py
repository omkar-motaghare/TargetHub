from sqlalchemy.orm import Session

from app.models.agent import Agent, AgentResource


class AgentRepository:
    def __init__(self, db: Session):
        self.db = db

    def list(self):
        return self.db.query(Agent).order_by(Agent.name).all()

    def get(self, agent_id: str):
        return self.db.query(Agent).filter(Agent.id == agent_id).first()

    def get_by_name(self, name: str):
        return self.db.query(Agent).filter(Agent.name == name).first()

    def create(self, agent: Agent):
        self.db.add(agent)
        self.db.commit()
        self.db.refresh(agent)
        return agent

    def save(self, agent: Agent):
        self.db.commit()
        self.db.refresh(agent)
        return agent

    def replace_resources(self, agent: Agent, resources: list[AgentResource]):
        agent.resources.clear()
        agent.resources.extend(resources)
        self.db.commit()
        self.db.refresh(agent)
        return agent
