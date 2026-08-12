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


def test_duplicate_agent_name_is_rejected():
    repository = FakeRepository()
    service = AgentService(repository)

    first_enrollment, first_token = service.create_enrollment("agent-duplicate")
    service.enroll(first_token, "linux-host-01")

    with pytest.raises(Exception, match="already registered"):
        service.create_enrollment("agent-duplicate")


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
