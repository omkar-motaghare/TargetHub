from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

os.environ.setdefault("SECRET_KEY", "test-secret-key")

import pytest

from app.core.exceptions import ConflictResource
from app.models.agent_operation import AgentOperation
from app.services.agent_operation_service import AgentOperationService


@dataclass
class FakeSession:
    id: str
    capability_type: str
    agent_id: str
    resource_id: str
    status: str = "active"
    expires_at: datetime = field(
        default_factory=lambda: datetime.now(UTC) + timedelta(minutes=5)
    )


@dataclass
class FakeResource:
    id: str
    agent_id: str
    resource_key: str
    resource_type: str = "serial"
    resource_metadata: dict = field(default_factory=dict)
    available: bool = True


class FakeOperationRepository:
    def __init__(self, *, auto_complete: bool = False):
        self.items: dict[str, AgentOperation] = {}
        self.auto_complete = auto_complete

    def create(self, entry: AgentOperation) -> AgentOperation:
        self.items[entry.id] = entry
        if self.auto_complete:
            entry.status = "completed"
            entry.detail = "ok"
            entry.result_data = {"echo": entry.params}
            entry.completed_at = datetime.now(UTC)
        return entry

    def get(self, operation_id: str) -> AgentOperation | None:
        return self.items.get(operation_id)

    def save(self, entry: AgentOperation) -> AgentOperation:
        self.items[entry.id] = entry
        return entry

    def expire_stale(self, *, agent_id, now, pending_before):
        return 0

    def claim_next(self, *, agent_id, now, lease_expires_at, allowed_operations):
        candidates = sorted(self.items.values(), key=lambda item: item.requested_at or now)
        for item in candidates:
            if item.agent_id != agent_id:
                continue
            if item.operation not in allowed_operations:
                continue
            expired_lease = (
                item.status == "in_progress"
                and item.lease_expires_at is not None
                and item.lease_expires_at <= now
            )
            if item.status not in {"pending", "in_progress"} or (item.status == "in_progress" and not expired_lease):
                continue
            item.status = "in_progress"
            item.dispatched_at = now
            item.lease_expires_at = lease_expires_at
            return item
        return None


class FakeSessionRepository:
    def __init__(self, sessions: list[FakeSession]):
        self.sessions = {item.id: item for item in sessions}

    def get(self, session_id: str):
        return self.sessions.get(session_id)


class FakeAgentRepository:
    def __init__(self, resources: list[FakeResource]):
        self.resources = {item.id: item for item in resources}

    def get_resource(self, resource_id: str):
        return self.resources.get(resource_id)


def _service(
    session: FakeSession,
    resource: FakeResource,
    *,
    auto_complete: bool = False,
    timeout_seconds: float = 1.0,
) -> tuple[AgentOperationService, FakeOperationRepository]:
    operation_repo = FakeOperationRepository(auto_complete=auto_complete)
    service = AgentOperationService(
        operation_repo,
        FakeSessionRepository([session]),
        FakeAgentRepository([resource]),
        operation_timeout_seconds=timeout_seconds,
        poll_interval_seconds=0.05,
    )
    return service, operation_repo


def test_execute_serial_enqueues_allowlisted_operation_and_waits_for_result():
    session = FakeSession(id="s1", capability_type="serial", agent_id="a1", resource_id="r1")
    resource = FakeResource(id="r1", agent_id="a1", resource_key="sim://uart0")
    service, operation_repo = _service(session, resource, auto_complete=True)

    result = service.execute_serial(
        session=session,
        user_id="user1",
        operation="write",
        params={"text": "hello"},
    )

    assert result["message"] == "ok"
    stored = next(iter(operation_repo.items.values()))
    assert stored.operation == "write"
    assert stored.params == {"text": "hello"}
    assert stored.resource_key == "sim://uart0"


def test_execute_serial_rejects_non_allowlisted_operation():
    session = FakeSession(id="s1", capability_type="serial", agent_id="a1", resource_id="r1")
    resource = FakeResource(id="r1", agent_id="a1", resource_key="sim://uart0")
    service, _repo = _service(session, resource, auto_complete=True)

    with pytest.raises(ConflictResource, match="not supported"):
        service.execute_serial(session=session, user_id="user1", operation="exec", params={})


def test_execute_serial_times_out_with_clear_disconnect_error():
    session = FakeSession(id="s1", capability_type="serial", agent_id="a1", resource_id="r1")
    resource = FakeResource(id="r1", agent_id="a1", resource_key="sim://uart0")
    service, operation_repo = _service(session, resource, auto_complete=False, timeout_seconds=0.2)

    with pytest.raises(ConflictResource, match="offline or disconnected"):
        service.execute_serial(
            session=session,
            user_id="user1",
            operation="open",
            params={},
        )

    stored = next(iter(operation_repo.items.values()))
    assert stored.status == "timed_out"


def test_poll_for_agent_cancels_operation_if_session_expired():
    expired_session = FakeSession(
        id="s1",
        capability_type="serial",
        agent_id="a1",
        resource_id="r1",
        expires_at=datetime.now(UTC) - timedelta(seconds=1),
    )
    resource = FakeResource(id="r1", agent_id="a1", resource_key="sim://uart0")
    service, operation_repo = _service(expired_session, resource, auto_complete=False)

    pending = AgentOperation(
        agent_id="a1",
        session_id="s1",
        resource_id="r1",
        resource_key=resource.resource_key,
        resource_type="serial",
        resource_metadata={},
        operation="open",
        params={},
        status="pending",
    )
    operation_repo.create(pending)

    claimed = service.poll_for_agent(agent_id="a1", wait_seconds=0, lease_seconds=10)
    assert claimed is None
    assert pending.status == "cancelled"


def test_poll_for_agent_cancels_operation_if_session_closed():
    closed_session = FakeSession(
        id="s1",
        capability_type="serial",
        agent_id="a1",
        resource_id="r1",
        status="closed",
    )
    resource = FakeResource(id="r1", agent_id="a1", resource_key="sim://uart0")
    service, operation_repo = _service(closed_session, resource, auto_complete=False)

    pending = AgentOperation(
        agent_id="a1",
        session_id="s1",
        resource_id="r1",
        resource_key=resource.resource_key,
        resource_type="serial",
        resource_metadata={},
        operation="open",
        params={},
        status="pending",
    )
    operation_repo.create(pending)

    claimed = service.poll_for_agent(agent_id="a1", wait_seconds=0, lease_seconds=10)
    assert claimed is None
    assert pending.status == "cancelled"


def test_complete_for_agent_rejects_foreign_agent():
    session = FakeSession(id="s1", capability_type="serial", agent_id="a1", resource_id="r1")
    resource = FakeResource(id="r1", agent_id="a1", resource_key="sim://uart0")
    service, operation_repo = _service(session, resource, auto_complete=False)

    pending = AgentOperation(
        agent_id="a1",
        session_id="s1",
        resource_id="r1",
        resource_key=resource.resource_key,
        resource_type="serial",
        resource_metadata={},
        operation="open",
        params={},
        status="in_progress",
    )
    operation_repo.create(pending)

    with pytest.raises(ConflictResource, match="does not belong"):
        service.complete_for_agent(
            agent_id="a2",
            operation_id=pending.id,
            success=True,
            message="ok",
            data={},
        )


def test_power_session_queues_power_operation_for_agent():
    session = FakeSession(id="s1", capability_type="reset", agent_id="a1", resource_id="r1")
    resource = FakeResource(id="r1", agent_id="a1", resource_key="power:relay1", resource_type="power")
    service, operation_repo = _service(session, resource, auto_complete=True)

    service.execute_for_session(session=session, user_id="user1", operation="cycle", params={})

    stored = next(iter(operation_repo.items.values()))
    assert (stored.operation, stored.resource_type) == ("cycle", "power")
    with pytest.raises(ConflictResource, match="not supported"):
        service.execute_for_session(session=session, user_id="user1", operation="read", params={})


def test_deploy_requires_url_and_sha256():
    session = FakeSession(id="s1", capability_type="deploy", agent_id="a1", resource_id="r1")
    resource = FakeResource(id="r1", agent_id="a1", resource_key="deploy:flash", resource_type="deploy")
    service, operation_repo = _service(session, resource, auto_complete=True)

    for params in ({}, {"url": "ftp://x/fw", "sha256": "a" * 64}, {"url": "https://x/fw", "sha256": "xyz"}):
        with pytest.raises(ConflictResource):
            service.execute_for_session(session=session, user_id="user1", operation="deploy", params=params)

    service.execute_for_session(
        session=session,
        user_id="user1",
        operation="deploy",
        params={"url": "https://x/fw", "sha256": "A" * 64},
    )
    assert next(iter(operation_repo.items.values())).params["sha256"] == "a" * 64
