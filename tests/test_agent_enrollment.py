import os
from datetime import timedelta

os.environ.setdefault("SECRET_KEY", "test-secret-key")

import pytest

from app.models.agent import Agent
from app.services.agent_service import AgentService


class FakeRepository:
    def __init__(self):
        self.agents = []
        self.enrollments = []

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
        self.agents.append(agent)
        return agent

    def create_enrollment(self, enrollment):
        self.enrollments.append(enrollment)
        return enrollment

    def save(self, agent):
        return agent

    def save_enrollment(self, enrollment):
        return enrollment


def test_enrollment_is_single_use_and_credential_authenticates():
    repository = FakeRepository()
    service = AgentService(repository)

    enrollment, token = service.create_enrollment("pi-01", "remote_raspberry_pi")
    assert token
    assert enrollment.used_at is None
    assert enrollment.token_hash != token

    agent, credential = service.enroll(token, "raspberrypi", "raspberry_pi")
    assert agent.name == "pi-01"
    assert agent.hostname == "raspberrypi"
    assert credential.startswith("agent_")
    assert agent.credential_hash != credential
    assert enrollment.used_at is not None

    assert service.authenticate_credential(credential) is agent

    with pytest.raises(Exception, match="already been used"):
        service.enroll(token, "raspberrypi", "raspberry_pi")


def test_expired_enrollment_is_rejected():
    repository = FakeRepository()
    service = AgentService(repository)

    enrollment, token = service.create_enrollment("pi-expired", "raspberry_pi_all_in_one")
    enrollment.expires_at = enrollment.expires_at - timedelta(days=1)

    with pytest.raises(Exception, match="expired"):
        service.enroll(token, "raspberrypi", "raspberry_pi")


def test_disabled_agent_cannot_authenticate():
    repository = FakeRepository()
    service = AgentService(repository)

    enrollment, token = service.create_enrollment("linux-01", "same_linux")
    agent, credential = service.enroll(token, "linux-host", "linux")
    service.disable(agent.id)

    with pytest.raises(Exception, match="disabled"):
        service.authenticate_credential(credential)


def test_multiple_agents_can_enroll_from_the_same_host():
    repository = FakeRepository()
    service = AgentService(repository)

    enrollment_a, token_a = service.create_enrollment("linux-agent-a", "same_linux")
    enrollment_b, token_b = service.create_enrollment("linux-agent-b", "same_linux")

    agent_a, credential_a = service.enroll(token_a, "same-linux-host", "linux")
    agent_b, credential_b = service.enroll(token_b, "same-linux-host", "linux")

    assert agent_a.id != agent_b.id
    assert agent_a.name != agent_b.name
    assert credential_a != credential_b
    assert agent_a.hostname == agent_b.hostname == "same-linux-host"
    assert service.authenticate_credential(credential_a) is agent_a
    assert service.authenticate_credential(credential_b) is agent_b
    assert enrollment_a.agent_id == agent_a.id
    assert enrollment_b.agent_id == agent_b.id


def test_raspberry_pi_enrollment_is_rejected_on_linux_host():
    repository = FakeRepository()
    service = AgentService(repository)

    enrollment, token = service.create_enrollment("pi-01", "remote_raspberry_pi")

    with pytest.raises(Exception, match="requires the Agent to run on a Raspberry Pi"):
        service.enroll(token, "linux-host", "linux")

    assert enrollment.used_at is None
    assert repository.agents == []


def test_same_linux_enrollment_is_rejected_on_raspberry_pi():
    repository = FakeRepository()
    service = AgentService(repository)

    enrollment, token = service.create_enrollment("linux-01", "same_linux")

    with pytest.raises(Exception, match="same Linux machine"):
        service.enroll(token, "raspberrypi", "raspberry_pi")

    assert enrollment.used_at is None
    assert repository.agents == []
