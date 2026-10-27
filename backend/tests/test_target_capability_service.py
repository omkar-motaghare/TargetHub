import os
from dataclasses import dataclass

os.environ.setdefault("SECRET_KEY", "test-secret-key")

import pytest
from app.core.exceptions import ConflictResource, ResourceNotFound
from app.services.target_capability_service import TargetCapabilityService


@dataclass
class FakeTarget:
    id: str


@dataclass
class FakeAgent:
    id: str
    enabled: bool = True


@dataclass
class FakeResource:
    id: str
    agent_id: str
    resource_type: str
    available: bool = True


class FakeTargetRepository:
    def __init__(self, targets):
        self.targets = {target.id: target for target in targets}

    def get(self, target_id):
        return self.targets.get(target_id)


class FakeCapabilityRepository:
    def __init__(self):
        self.by_target_name = {}
        self.created = []

    def list_for_target(self, target_id):
        return []

    def get(self, target_id, capability_id):
        return None

    def get_by_name(self, target_id, name):
        return self.by_target_name.get((target_id, name))

    def create(self, capability):
        self.created.append(capability)
        self.by_target_name[(capability.target_id, capability.name)] = capability
        return capability

    def update(self, capability):
        return capability

    def delete(self, capability):
        return None


class FakeAgentRepository:
    def __init__(self, agents, resources):
        self.agents = {agent.id: agent for agent in agents}
        self.resources = {resource.id: resource for resource in resources}

    def get(self, agent_id):
        return self.agents.get(agent_id)

    def get_resource(self, resource_id):
        return self.resources.get(resource_id)


def _service(*, agent_enabled=True, resource_available=True, resource_type="serial"):
    target_repo = FakeTargetRepository([FakeTarget(id="t1")])
    capability_repo = FakeCapabilityRepository()
    agent_repo = FakeAgentRepository(
        [FakeAgent(id="a1", enabled=agent_enabled)],
        [FakeResource(id="r1", agent_id="a1", resource_type=resource_type, available=resource_available)],
    )
    return TargetCapabilityService(capability_repo, target_repo, agent_repo)


def test_create_capability_requires_agent_and_resource_pair():
    service = _service()
    with pytest.raises(ConflictResource, match="requires both agent_id and resource_id"):
        service.create_capability(
            "t1",
            name="Serial",
            capability_type="serial",
            agent_id="a1",
            resource_id=None,
            provider_key="serial-demo",
            provider_config={},
            enabled=True,
        )


def test_create_capability_can_be_unmapped():
    service = _service()
    created = service.create_capability(
        "t1",
        name="Serial",
        capability_type="serial",
        agent_id=None,
        resource_id=None,
        provider_key="serial-demo",
        provider_config={},
        enabled=True,
    )
    assert created.agent_id is None
    assert created.resource_id is None


def test_create_capability_rejects_missing_agent():
    service = _service()
    with pytest.raises(ResourceNotFound, match="Agent 'missing' not found"):
        service.create_capability(
            "t1",
            name="Serial",
            capability_type="serial",
            agent_id="missing",
            resource_id="r1",
            provider_key="serial-demo",
            provider_config={},
            enabled=True,
        )


def test_create_capability_rejects_disabled_agent():
    service = _service(agent_enabled=False)
    with pytest.raises(ConflictResource, match="Agent is disabled"):
        service.create_capability(
            "t1",
            name="Serial",
            capability_type="serial",
            agent_id="a1",
            resource_id="r1",
            provider_key="serial-demo",
            provider_config={},
            enabled=True,
        )


def test_create_capability_rejects_incompatible_resource_type():
    service = _service(resource_type="power")
    with pytest.raises(ConflictResource, match="incompatible"):
        service.create_capability(
            "t1",
            name="Serial",
            capability_type="serial",
            agent_id="a1",
            resource_id="r1",
            provider_key="serial-demo",
            provider_config={},
            enabled=True,
        )


def test_create_capability_rejects_unavailable_resource_when_enabled():
    service = _service(resource_available=False)
    with pytest.raises(ConflictResource, match="unavailable"):
        service.create_capability(
            "t1",
            name="Serial",
            capability_type="serial",
            agent_id="a1",
            resource_id="r1",
            provider_key="serial-demo",
            provider_config={},
            enabled=True,
        )


def test_create_capability_allows_unavailable_resource_when_disabled():
    service = _service(resource_available=False)
    created = service.create_capability(
        "t1",
        name="Serial",
        capability_type="serial",
        agent_id="a1",
        resource_id="r1",
        provider_key="serial-demo",
        provider_config={},
        enabled=False,
    )
    assert created.enabled is False