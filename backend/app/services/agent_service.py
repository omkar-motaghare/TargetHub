from datetime import datetime, timezone

from app.core.exceptions import TargetHubException
from app.models.agent import Agent, AgentResource
from app.repositories.agent_repository import AgentRepository


class AgentService:
    def __init__(self, repository: AgentRepository):
        self.repository = repository

    def list_agents(self):
        return self.repository.list()

    def get_agent(self, agent_id: str):
        agent = self.repository.get(agent_id)
        if not agent:
            raise TargetHubException("Agent not found", status_code=404)
        return agent

    def register(self, name: str, hostname: str | None):
        agent = self.repository.get_by_name(name)
        if agent:
            agent.hostname = hostname or agent.hostname
            agent.status = "online"
            agent.last_seen_at = datetime.now(timezone.utc)
            return self.repository.save(agent)
        return self.repository.create(
            Agent(name=name, hostname=hostname, status="online", last_seen_at=datetime.now(timezone.utc))
        )

    def heartbeat(self, agent_id: str, hostname: str | None, resources):
        agent = self.get_agent(agent_id)
        if not agent.enabled:
            raise TargetHubException("Agent is disabled", status_code=409)
        agent.hostname = hostname or agent.hostname
        agent.status = "online"
        agent.last_seen_at = datetime.now(timezone.utc)
        agent.resources.clear()
        for item in resources:
            agent.resources.append(
                AgentResource(
                    resource_key=item.resource_key,
                    resource_type=item.resource_type,
                    display_name=item.display_name,
                    metadata=item.metadata,
                    available=item.available,
                )
            )
        return self.repository.save(agent)
