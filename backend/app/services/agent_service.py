import hashlib
import hmac
import os
import secrets
from datetime import UTC, datetime, timedelta

from app.core.config import settings
from app.core.exceptions import AuthenticationError, ConflictResource, ResourceNotFound
from app.models.agent import Agent, AgentEnrollment, AgentResource
from app.repositories.agent_repository import AgentRepository
from app.services.notifier import Notifier

ENROLLMENT_TTL_MINUTES = 30
AGENT_OFFLINE_AFTER_SECONDS = int(os.getenv("TARGETHUB_AGENT_OFFLINE_AFTER_SECONDS", "45"))


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
        return datetime.now(UTC)

    def _stale(self, agents: list[Agent]) -> list[Agent]:
        cutoff = self._now() - timedelta(seconds=AGENT_OFFLINE_AFTER_SECONDS)
        stale = []
        for agent in agents:
            if agent.status != "online" or not agent.last_seen_at:
                continue
            last_seen = agent.last_seen_at
            if last_seen.tzinfo is None:
                last_seen = last_seen.replace(tzinfo=UTC)
            if last_seen < cutoff:
                stale.append(agent)
        return stale

    def _announce(self, agent: Agent, event: str) -> None:
        db = getattr(self.repository, "db", None)
        if db is None:  # in-memory repositories used by unit tests
            return
        state = "stopped sending heartbeats" if event == "agent.offline" else "is back online"
        Notifier(db).event(
            event,
            f"Agent '{agent.name}' ({agent.hostname or 'unknown host'}) {state}",
            data={"agent": agent.name, "hostname": agent.hostname},
        )

    def _mark_offline(self, agents: list[Agent]) -> list[Agent]:
        changed = self._stale(agents)
        for agent in changed:
            agent.status = "offline"
            self.repository.save(agent)
            self._announce(agent, "agent.offline")
        return changed

    def _refresh_liveness(self, agents: list[Agent]):
        self._mark_offline(agents)
        return agents

    def mark_stale_offline(self) -> list[Agent]:
        """Flip online Agents without a recent heartbeat to offline (and announce it)."""
        return self._mark_offline(self.repository.list())

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

    def create_enrollment(self, agent_name: str):
        agent_name = agent_name.strip()
        if not agent_name:
            raise ConflictResource("Agent name is required")

        existing = self.repository.get_by_name(agent_name)
        if existing is not None:
            # A healthy/active Agent already owns this identity. Reusing the
            # name would unexpectedly replace its credential. A disabled or
            # revoked Agent may be explicitly re-enrolled instead.
            credential_active = (
                existing.enabled
                and existing.credential_hash is not None
                and existing.credential_revoked_at is None
            )
            if credential_active:
                raise ConflictResource(f"Agent name '{agent_name}' is already registered")

        token = self._new_secret("enroll")
        enrollment = AgentEnrollment(
            agent_name=agent_name,
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
            expires_at = expires_at.replace(tzinfo=UTC)
        if expires_at <= self._now():
            raise ConflictResource("Enrollment token has expired")

        now = self._now()
        if not self.repository.claim_enrollment(enrollment.id, now):
            raise ConflictResource("Enrollment token has already been used")

        agent = self.repository.get_by_name(enrollment.agent_name)
        if agent is None:
            agent = Agent(name=enrollment.agent_name)
            self.repository.create(agent)

        credential = self._new_secret("agent")
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

    def heartbeat(
        self,
        agent: Agent,
        hostname: str | None,
        resources,
        agent_version: str | None = None,
        platform: str | None = None,
    ):
        if not agent.enabled:
            raise ConflictResource("Agent is disabled")
        agent.hostname = hostname or agent.hostname
        agent.agent_version = agent_version or agent.agent_version
        agent.platform = platform or agent.platform
        came_back = agent.status == "offline"
        agent.status = "online"
        agent.last_seen_at = self._now()

        existing_by_key = {(item.resource_key, item.resource_type): item for item in agent.resources}
        seen_keys: set[tuple[str, str]] = set()
        next_resources: list[AgentResource] = []

        for item in resources:
            key = (item.resource_key, item.resource_type)
            if key in seen_keys:
                continue
            seen_keys.add(key)

            current = existing_by_key.get(key)
            if current is None:
                current = AgentResource(
                    resource_key=item.resource_key,
                    resource_type=item.resource_type,
                    display_name=item.display_name,
                    resource_metadata=item.metadata,
                    available=item.available,
                )
            else:
                current.display_name = item.display_name
                current.resource_metadata = item.metadata
                current.available = item.available

            next_resources.append(current)

        agent.resources[:] = next_resources
        saved = self.repository.save(agent)
        if came_back:
            self._announce(saved, "agent.online")
        return saved

    def disable(self, agent_id: str):
        agent = self.get_agent(agent_id)
        agent.enabled = False
        agent.status = "disabled"
        self.repository.save(agent)
        self.repository.disable_capabilities_for_agent(agent.id)
        return self.get_agent(agent_id)

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
        self.repository.save(agent)
        self.repository.disable_capabilities_for_agent(agent.id)
        return self.get_agent(agent_id)
