import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone

from app.core.config import settings
from app.core.exceptions import AuthenticationError, ConflictResource, ResourceNotFound
from app.models.agent import Agent, AgentEnrollment, AgentResource
from app.repositories.agent_repository import AgentRepository


ENROLLMENT_TTL_MINUTES = 30
AGENT_OFFLINE_AFTER_SECONDS = 45


class AgentService:
    def __init__(self, repository: AgentRepository):
        self.repository = repository

    @staticmethod
    def _hash_secret(value: str) -> str:
        return hmac.new(
            settings.secret_key.encode("utf-8"),
            value.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

    @staticmethod
    def _new_secret(prefix: str) -> str:
        return f"{prefix}_{secrets.token_urlsafe(32)}"

    @staticmethod
    def _now() -> datetime:
        return datetime.now(timezone.utc)

    def _refresh_liveness(self, agents: list[Agent]):
        cutoff = self._now() - timedelta(seconds=AGENT_OFFLINE_AFTER_SECONDS)
        changed = False
        for agent in agents:
            if agent.status != "online" or not agent.last_seen_at:
                continue
            last_seen = agent.last_seen_at
            if last_seen.tzinfo is None:
                last_seen = last_seen.replace(tzinfo=timezone.utc)
            if last_seen < cutoff:
                agent.status = "offline"
                changed = True
        if changed:
            for agent in agents:
                if agent.status == "offline":
                    self.repository.save(agent)
        return agents

    def list_agents(self):
        return self._refresh_liveness(self.repository.list())

    def list_enrollments(self):
        return self.repository.list_enrollments()

    def get_agent(self, agent_id: str):
        agent = self.repository.get(agent_id)
        if not agent:
            raise ResourceNotFound("Agent", agent_id)
        self._refresh_liveness([agent])
        return agent

    def create_enrollment(self, agent_name: str, deployment_scenario: str):
        if not agent_name.strip():
            raise ConflictResource("Agent name is required")

        token = self._new_secret("enroll")
        enrollment = AgentEnrollment(
            agent_name=agent_name.strip(),
            deployment_scenario=deployment_scenario,
            token_hash=self._hash_secret(token),
            expires_at=self._now() + timedelta(minutes=ENROLLMENT_TTL_MINUTES),
        )
        self.repository.create_enrollment(enrollment)
        return enrollment, token

    def enroll(self, token: str, hostname: str | None):
        enrollment = self.repository.get_enrollment_by_token_hash(self._hash_secret(token))
        if not enrollment:
            raise AuthenticationError("Invalid enrollment token")
        if enrollment.used_at is not None:
            raise ConflictResource("Enrollment token has already been used")

        expires_at = enrollment.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if expires_at <= self._now():
            raise ConflictResource("Enrollment token has expired")

        agent = self.repository.get_by_name(enrollment.agent_name)
        if agent is None:
            agent = Agent(name=enrollment.agent_name)
            self.repository.create(agent)

        credential = self._new_secret("agent")
        now = self._now()
        agent.hostname = hostname or agent.hostname
        agent.status = "online"
        agent.enabled = True
        agent.last_seen_at = now
        agent.credential_hash = self._hash_secret(credential)
        agent.credential_prefix = credential[:12]
        agent.credential_created_at = now
        agent.credential_revoked_at = None
        self.repository.save(agent)

        enrollment.agent_id = agent.id
        enrollment.used_at = now
        self.repository.save_enrollment(enrollment)
        return agent, credential

    def authenticate_credential(self, credential: str):
        agent = self.repository.get_by_credential_hash(self._hash_secret(credential))
        if not agent or not agent.enabled:
            raise AuthenticationError("Invalid or disabled Agent credential")
        if agent.credential_revoked_at is not None:
            raise AuthenticationError("Agent credential has been revoked")
        return agent

    def register(self, name: str, hostname: str | None):
        """Legacy registration kept for compatibility; new deployments should enroll."""
        agent = self.repository.get_by_name(name)
        if agent:
            agent.hostname = hostname or agent.hostname
            agent.status = "online"
            agent.last_seen_at = self._now()
            return self.repository.save(agent)
        return self.repository.create(
            Agent(name=name, hostname=hostname, status="online", last_seen_at=self._now())
        )

    def heartbeat(self, agent: Agent, hostname: str | None, resources):
        if not agent.enabled:
            raise ConflictResource("Agent is disabled")
        agent.hostname = hostname or agent.hostname
        agent.status = "online"
        agent.last_seen_at = self._now()
        agent.resources.clear()
        for item in resources:
            agent.resources.append(
                AgentResource(
                    resource_key=item.resource_key,
                    resource_type=item.resource_type,
                    display_name=item.display_name,
                    resource_metadata=item.metadata,
                    available=item.available,
                )
            )
        return self.repository.save(agent)

    def disable(self, agent_id: str):
        agent = self.get_agent(agent_id)
        agent.enabled = False
        agent.status = "disabled"
        return self.repository.save(agent)

    def enable(self, agent_id: str):
        agent = self.get_agent(agent_id)
        agent.enabled = True
        if agent.status == "disabled":
            agent.status = "offline"
        return self.repository.save(agent)

    def revoke_credential(self, agent_id: str):
        agent = self.get_agent(agent_id)
        agent.credential_hash = None
        agent.credential_prefix = None
        agent.credential_revoked_at = self._now()
        agent.status = "offline" if agent.enabled else "disabled"
        return self.repository.save(agent)
