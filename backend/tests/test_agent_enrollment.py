import os
import uuid
from datetime import timedelta

os.environ.setdefault("SECRET_KEY", "test-secret-key")

import pytest
from pydantic import ValidationError

from app.core.exceptions import ConflictResource
from app.schemas.agent import AgentHeartbeat
from app.services.agent_service import AgentService


class FakeRepository:
    def __init__(self):
        self.agents = []
        self.enrollments = []
        self.disabled_capabilities_for_agents = []

    def list(self):
        return self.agents

    def list_enrollments(self):
        return self.enrollments

    def get(self, agent_id):
        return next((agent for agent in self.agents if agent.id == agent_id), None)

    def get_by_name(self, name):
        return next((agent for agent in self.agents if agent.name == name), None)

    def get_by_credential_hash(self, credential_hash):
        return next((agent for agent in self.agents if agent.credential_hash == credential_hash), None)

    def get_enrollment_by_token_hash(self, token_hash):
        return next((item for item in self.enrollments if item.token_hash == token_hash), None)

    def create(self, agent):
        if not agent.id:
            agent.id = str(uuid.uuid4())
        self.agents.append(agent)
        return agent

    def create_enrollment(self, enrollment):
        if not enrollment.id:
            enrollment.id = str(uuid.uuid4())
        self.enrollments.append(enrollment)
        return enrollment

    def save(self, agent):
        return agent

    def save_enrollment(self, enrollment):
        return enrollment

    def claim_enrollment(self, enrollment_id, used_at):
        enrollment = next(item for item in self.enrollments if item.id == enrollment_id)
        if enrollment.used_at is not None:
            return False
        enrollment.used_at = used_at
        return True

    def disable_capabilities_for_agent(self, agent_id):
        self.disabled_capabilities_for_agents.append(agent_id)
        return 1


def test_enrollment_is_single_use_and_credential_authenticates():
    repository = FakeRepository()
    service = AgentService(repository)

    enrollment, token = service.create_enrollment("agent-01")
    assert token
    assert enrollment.used_at is None
    assert enrollment.token_hash != token

    agent, credential = service.enroll(token, "raspberrypi")
    assert agent.name == "agent-01"
    assert agent.hostname == "raspberrypi"
    assert credential.startswith("agent_")
    assert agent.credential_hash != credential
    assert enrollment.used_at is not None

    assert service.authenticate_credential(credential) is agent

    with pytest.raises(Exception, match="already been used"):
        service.enroll(token, "raspberrypi")


def test_expired_enrollment_is_rejected():
    repository = FakeRepository()
    service = AgentService(repository)

    enrollment, token = service.create_enrollment("agent-expired")
    enrollment.expires_at = enrollment.expires_at - timedelta(days=1)

    with pytest.raises(Exception, match="expired"):
        service.enroll(token, "linux-host")


def test_duplicate_active_agent_name_is_rejected():
    repository = FakeRepository()
    service = AgentService(repository)

    first_enrollment, first_token = service.create_enrollment("agent-duplicate")
    service.enroll(first_token, "linux-host-01")

    with pytest.raises(Exception, match="already registered"):
        service.create_enrollment("agent-duplicate")


def test_revoked_agent_can_be_reenrolled_with_same_name():
    repository = FakeRepository()
    service = AgentService(repository)

    first_enrollment, first_token = service.create_enrollment("agent-reenroll")
    agent, old_credential = service.enroll(first_token, "linux-host-01")
    service.revoke_credential(agent.id)

    second_enrollment, second_token = service.create_enrollment("agent-reenroll")
    assert second_enrollment.agent_name == "agent-reenroll"

    re_enrolled, new_credential = service.enroll(second_token, "linux-host-02")
    assert re_enrolled is agent
    assert new_credential != old_credential
    assert re_enrolled.hostname == "linux-host-02"
    assert service.authenticate_credential(new_credential) is agent

    with pytest.raises(Exception, match="Invalid or disabled"):
        service.authenticate_credential(old_credential)


def test_multiple_agents_can_share_the_same_linux_host():
    repository = FakeRepository()
    service = AgentService(repository)

    first_enrollment, first_token = service.create_enrollment("agent-linux-01")
    second_enrollment, second_token = service.create_enrollment("agent-linux-02")

    first_agent, first_credential = service.enroll(first_token, "linux-host")
    second_agent, second_credential = service.enroll(second_token, "linux-host")

    assert first_agent.id != second_agent.id
    assert first_agent.hostname == second_agent.hostname == "linux-host"
    assert first_credential != second_credential
    assert len(repository.agents) == 2


def test_disabled_agent_cannot_authenticate():
    repository = FakeRepository()
    service = AgentService(repository)

    enrollment, token = service.create_enrollment("linux-01")
    agent, credential = service.enroll(token, "linux-host")
    service.disable(agent.id)

    with pytest.raises(Exception, match="disabled"):
        service.authenticate_credential(credential)


def test_disabled_agent_can_be_reenrolled_with_same_name():
    repository = FakeRepository()
    service = AgentService(repository)

    first_enrollment, first_token = service.create_enrollment("agent-disabled")
    agent, old_credential = service.enroll(first_token, "linux-host-01")
    service.disable(agent.id)

    second_enrollment, second_token = service.create_enrollment("agent-disabled")
    re_enrolled, new_credential = service.enroll(second_token, "linux-host-02")

    assert re_enrolled is agent
    assert re_enrolled.enabled is True
    assert re_enrolled.status == "online"
    assert new_credential != old_credential


def test_revoke_credential_clears_stored_credential_material():
    """Revocation must not leave any usable credential material behind server-side."""
    repository = FakeRepository()
    service = AgentService(repository)

    enrollment, token = service.create_enrollment("agent-wipe")
    agent, credential = service.enroll(token, "linux-host")
    assert agent.credential_hash is not None
    assert agent.credential_prefix is not None

    service.revoke_credential(agent.id)

    assert agent.credential_hash is None
    assert agent.credential_prefix is None
    assert agent.credential_revoked_at is not None
    with pytest.raises(Exception, match="Invalid or disabled|revoked"):
        service.authenticate_credential(credential)


def test_disable_and_revoke_disable_mapped_capabilities():
    repository = FakeRepository()
    service = AgentService(repository)

    enrollment, token = service.create_enrollment("agent-disable-capabilities")
    agent, _credential = service.enroll(token, "linux-host")

    service.disable(agent.id)
    service.revoke_credential(agent.id)

    assert repository.disabled_capabilities_for_agents.count(agent.id) == 2


def test_heartbeat_preserves_resource_id_for_same_resource_key():
    repository = FakeRepository()
    service = AgentService(repository)

    enrollment, token = service.create_enrollment("agent-resource-stable")
    agent, _ = service.enroll(token, "linux-host")
    first = service.heartbeat(
        agent,
        "linux-host",
        [
            type(
                "Resource",
                (),
                {
                    "resource_key": "/dev/serial/by-id/usb-abc",
                    "resource_type": "serial",
                    "display_name": "USB Serial",
                    "metadata": {"path": "/dev/ttyUSB0"},
                    "available": True,
                },
            )()
        ],
    )
    first_resource_id = first.resources[0].id

    second = service.heartbeat(
        agent,
        "linux-host",
        [
            type(
                "Resource",
                (),
                {
                    "resource_key": "/dev/serial/by-id/usb-abc",
                    "resource_type": "serial",
                    "display_name": "USB Serial Renamed",
                    "metadata": {"path": "/dev/ttyUSB0", "vendor": "acme"},
                    "available": False,
                },
            )()
        ],
    )

    assert second.resources[0].id == first_resource_id
    assert second.resources[0].display_name == "USB Serial Renamed"
    assert second.resources[0].resource_metadata["vendor"] == "acme"
    assert second.resources[0].available is False


def test_heartbeat_duplicate_entries_keep_single_resource():
    repository = FakeRepository()
    service = AgentService(repository)

    _enrollment, token = service.create_enrollment("agent-resource-dedupe")
    agent, _ = service.enroll(token, "linux-host")

    updated = service.heartbeat(
        agent,
        "linux-host",
        [
            type(
                "Resource",
                (),
                {
                    "resource_key": "/dev/ttyUSB0",
                    "resource_type": "serial",
                    "display_name": "ttyUSB0",
                    "metadata": {},
                    "available": True,
                },
            )(),
            type(
                "Resource",
                (),
                {
                    "resource_key": "/dev/ttyUSB0",
                    "resource_type": "serial",
                    "display_name": "ttyUSB0 duplicate",
                    "metadata": {},
                    "available": True,
                },
            )(),
        ],
    )

    assert len(updated.resources) == 1
    assert updated.resources[0].display_name == "ttyUSB0"


def test_heartbeat_rejects_malformed_resource_fields():
    with pytest.raises(ValidationError):
        AgentHeartbeat(
            resources=[
                {
                    "resource_key": "   ",
                    "resource_type": "serial",
                    "display_name": "ttyUSB0",
                }
            ]
        )

    with pytest.raises(ValidationError):
        AgentHeartbeat(
            resources=[
                {
                    "resource_key": "x" * 256,
                    "resource_type": "serial",
                    "display_name": "ttyUSB0",
                }
            ]
        )


def test_stale_online_agent_transitions_to_offline_on_list():
    repository = FakeRepository()
    service = AgentService(repository)

    _enrollment, token = service.create_enrollment("agent-stale")
    agent, _ = service.enroll(token, "linux-host")
    agent.last_seen_at = agent.last_seen_at - timedelta(seconds=120)

    listed = service.list_agents()
    assert listed[0].status == "offline"


def test_offline_agent_reconnects_to_online_on_heartbeat():
    repository = FakeRepository()
    service = AgentService(repository)

    _enrollment, token = service.create_enrollment("agent-reconnect")
    agent, _ = service.enroll(token, "linux-host")
    agent.status = "offline"
    agent.last_seen_at = agent.last_seen_at - timedelta(seconds=120)

    updated = service.heartbeat(agent, "linux-host", [])
    assert updated.status == "online"


def test_enroll_loses_race_when_token_already_claimed():
    repository = FakeRepository()
    service = AgentService(repository)
    _, token = service.create_enrollment("agent-race")
    # Another request claims the token between the used_at check and the claim.
    repository.claim_enrollment = lambda enrollment_id, used_at: False

    with pytest.raises(ConflictResource):
        service.enroll(token, "raspberrypi")
    assert repository.agents == []


def test_claim_enrollment_is_atomic_on_a_real_database(tmp_path):
    from datetime import UTC, datetime

    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.models.agent import AgentEnrollment
    from app.models.base import Base
    from app.repositories.agent_repository import AgentRepository

    engine = create_engine(f"sqlite:///{tmp_path / 'claim.sqlite3'}")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)
    with session_factory() as setup:
        enrollment = AgentEnrollment(
            agent_name="a", token_hash="h" * 64, expires_at=datetime.now(UTC) + timedelta(minutes=5)
        )
        setup.add(enrollment)
        setup.commit()
        enrollment_id = enrollment.id

    with session_factory() as first, session_factory() as second:
        assert AgentRepository(first).claim_enrollment(enrollment_id, datetime.now(UTC)) is True
        assert AgentRepository(second).claim_enrollment(enrollment_id, datetime.now(UTC)) is False
    engine.dispose()
