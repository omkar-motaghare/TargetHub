import os
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

os.environ.setdefault("SECRET_KEY", "test-secret-key")

import pytest

from app.core.exceptions import ConflictResource
from app.services.session_service import SessionService


@dataclass
class FakeCapability:
    capability_type: str
    id: str = "cap-1"
    enabled: bool = True
    provider_key: str | None = "prov-key"
    agent_id: str | None = "agent-1"
    resource_id: str | None = "res-1"
    agent: object | None = None
    resource: object | None = None


@dataclass
class FakeAgent:
    id: str
    enabled: bool = True
    status: str = "online"
    last_seen_at: datetime | None = field(
        default_factory=lambda: datetime.now(UTC)
    )
    credential_hash: str | None = "cred-hash"
    credential_revoked_at: datetime | None = None


@dataclass
class FakeResource:
    id: str
    agent_id: str
    resource_type: str = "serial"
    available: bool = True


@dataclass
class FakeTarget:
    id: str
    enabled: bool = True
    capabilities: list = field(default_factory=list)


@dataclass
class FakeReservation:
    id: str
    target_id: str
    user_id: str
    starts_at: datetime
    ends_at: datetime
    status: str = "active"


class FakeReservationRepo:
    def __init__(self, reservations):
        self.items = {r.id: r for r in reservations}

    def expire_due(self, now):
        return 0

    def get(self, reservation_id):
        return self.items.get(reservation_id)


class FakeTargetRepo:
    def __init__(self, targets):
        self.targets = {t.id: t for t in targets}

    def get(self, target_id):
        return self.targets.get(target_id)


class FakeSessionRepo:
    def __init__(self):
        self.items: list = []

    def expire_due(self, now):
        return 0

    def get(self, session_id):
        return next((s for s in self.items if s.id == session_id), None)

    def list(self, user_id=None, target_id=None):
        return self.items

    def create(self, session):
        self.items.append(session)
        return session

    def close(self, session, now, status="closed"):
        session.status = status
        session.ended_at = now
        return session

    def update(self, session):
        return session


def _active_reservation():
    now = datetime.now(UTC)
    return FakeReservation("r1", "t1", "user1", now - timedelta(minutes=1), now + timedelta(minutes=30))


def _service(reservation, target):
    return SessionService(
        FakeSessionRepo(),
        FakeReservationRepo([reservation]),
        FakeTargetRepo([target]),
    )


def _mapped_serial_capability(
    *,
    cap_id: str = "cap-serial-1",
    agent_status: str = "online",
    agent_enabled: bool = True,
    resource_available: bool = True,
    last_seen_delta_seconds: int = 0,
):
    now = datetime.now(UTC)
    agent = FakeAgent(
        id="agent-1",
        enabled=agent_enabled,
        status=agent_status,
        last_seen_at=now - timedelta(seconds=last_seen_delta_seconds),
    )
    resource = FakeResource(
        id="res-1",
        agent_id=agent.id,
        resource_type="serial",
        available=resource_available,
    )
    return FakeCapability(
        id=cap_id,
        capability_type="serial",
        enabled=True,
        provider_key="serial-1",
        agent_id=agent.id,
        resource_id=resource.id,
        agent=agent,
        resource=resource,
    )


def test_create_session_binds_provider_key():
    reservation = _active_reservation()
    target = FakeTarget("t1", capabilities=[_mapped_serial_capability()])
    service = _service(reservation, target)
    session = service.create_session("r1", "user1", "serial")
    assert session.provider_key == "serial-1"
    assert session.capability_id == "cap-serial-1"
    assert session.agent_id == "agent-1"
    assert session.resource_id == "res-1"
    assert session.status == "active"


def test_create_session_requires_owner():
    reservation = _active_reservation()
    target = FakeTarget("t1", capabilities=[_mapped_serial_capability()])
    service = _service(reservation, target)
    with pytest.raises(ConflictResource, match="owner"):
        service.create_session("r1", "intruder", "serial")


def test_create_session_requires_matching_capability():
    reservation = _active_reservation()
    target = FakeTarget("t1", capabilities=[_mapped_serial_capability()])
    service = _service(reservation, target)
    with pytest.raises(ConflictResource, match="capability"):
        service.create_session("r1", "user1", "power")


def test_close_session_requires_owner():
    reservation = _active_reservation()
    target = FakeTarget("t1", capabilities=[FakeCapability(
        id="cap-power-1",
        capability_type="power",
        provider_key="pdu-1",
        agent_id="agent-power",
        resource_id="res-power",
        agent=FakeAgent(id="agent-power"),
        resource=FakeResource(id="res-power", agent_id="agent-power", resource_type="power"),
    )])
    service = _service(reservation, target)
    session = service.create_session("r1", "user1", "power")
    with pytest.raises(ConflictResource, match="owner"):
        service.close_session(session.id, "intruder")
    closed = service.close_session(session.id, "user1")
    assert closed.status == "closed"


def test_create_session_requires_capability_id_when_multiple_same_type():
    reservation = _active_reservation()
    cap_a = _mapped_serial_capability(cap_id="cap-a")
    cap_b = _mapped_serial_capability(cap_id="cap-b")
    target = FakeTarget("t1", capabilities=[cap_a, cap_b])
    service = _service(reservation, target)
    with pytest.raises(ConflictResource, match="multiple enabled 'serial'"):
        service.create_session("r1", "user1", "serial")


def test_create_session_can_select_capability_by_id():
    reservation = _active_reservation()
    cap_a = _mapped_serial_capability(cap_id="cap-a")
    cap_b = _mapped_serial_capability(cap_id="cap-b")
    cap_b.provider_key = "serial-2"
    cap_b.resource.id = "res-2"
    cap_b.resource_id = "res-2"
    target = FakeTarget("t1", capabilities=[cap_a, cap_b])
    service = _service(reservation, target)

    session = service.create_session("r1", "user1", "serial", capability_id="cap-b")

    assert session.capability_id == "cap-b"
    assert session.provider_key == "serial-2"
    assert session.resource_id == "res-2"


def test_create_session_rejects_offline_agent():
    reservation = _active_reservation()
    target = FakeTarget("t1", capabilities=[_mapped_serial_capability(agent_status="offline")])
    service = _service(reservation, target)
    with pytest.raises(ConflictResource, match="offline"):
        service.create_session("r1", "user1", "serial")


def test_create_session_rejects_stale_heartbeat():
    reservation = _active_reservation()
    target = FakeTarget("t1", capabilities=[_mapped_serial_capability(last_seen_delta_seconds=120)])
    service = _service(reservation, target)
    with pytest.raises(ConflictResource, match="stale"):
        service.create_session("r1", "user1", "serial")


def test_create_session_rejects_unavailable_resource():
    reservation = _active_reservation()
    target = FakeTarget("t1", capabilities=[_mapped_serial_capability(resource_available=False)])
    service = _service(reservation, target)
    with pytest.raises(ConflictResource, match="unavailable"):
        service.create_session("r1", "user1", "serial")


def test_create_session_rejects_disabled_agent():
    reservation = _active_reservation()
    target = FakeTarget("t1", capabilities=[_mapped_serial_capability(agent_enabled=False)])
    service = _service(reservation, target)
    with pytest.raises(ConflictResource, match="disabled"):
        service.create_session("r1", "user1", "serial")
