import os
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

os.environ.setdefault("SECRET_KEY", "test-secret-key")

import pytest

from app.core.exceptions import ConflictResource, ResourceNotFound
from app.models.audit import AuditLog
from app.services.audit_service import AuditService
from app.services.provider_gateway import ProviderGateway


@dataclass
class FakeSession:
    id: str
    user_id: str
    target_id: str
    capability_type: str
    provider_key: str
    capability_id: str | None = "cap-1"
    agent_id: str | None = "agent-1"
    resource_id: str | None = "res-1"
    status: str = "active"
    expires_at: datetime = field(
        default_factory=lambda: datetime.now(UTC) + timedelta(minutes=30)
    )


class FakeSessionRepository:
    def __init__(self, sessions):
        self.sessions = {s.id: s for s in sessions}

    def expire_due(self, now):
        return 0

    def get(self, session_id):
        return self.sessions.get(session_id)


@dataclass
class FakeCapability:
    id: str
    capability_type: str
    provider_key: str
    agent_id: str
    resource_id: str
    enabled: bool = True
    provider_config: dict[str, Any] = field(default_factory=dict)
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
    credential_hash: str | None = "cred"
    credential_revoked_at: datetime | None = None


@dataclass
class FakeResource:
    id: str
    agent_id: str
    resource_type: str = "power"
    available: bool = True


@dataclass
class FakeTarget:
    id: str
    capabilities: list


class FakeTargetRepository:
    def __init__(self, targets):
        self.targets = {t.id: t for t in targets}

    def get(self, target_id):
        return self.targets.get(target_id)


class FakeAuditRepository:
    def __init__(self):
        self.entries = []

    def create(self, entry: AuditLog):
        self.entries.append(entry)
        return entry

    def list(self, **kwargs):
        return self.entries


class FakeAgentOperationService:
    def __init__(self):
        self.calls = []

    def execute_for_session(self, *, session, user_id, operation, params):
        self.calls.append((session.id, user_id, operation, params))
        if operation == "open":
            return {"message": "Serial connection opened", "data": {}}
        if operation == "write":
            text = str((params or {}).get("text", ""))
            return {"message": "Serial data written", "data": {"bytes_written": len(text)}}
        if operation == "read":
            payload = b"[simulated] console ready\r\n"
            return {
                "message": "Serial data read",
                "data": {"data": payload, "bytes_read": len(payload)},
            }
        if operation == "close":
            return {"message": "Serial connection closed", "data": {}}
        return {"message": "unsupported", "data": {}}


def _gateway(sessions, targets=None, operation_service=None):
    ProviderGateway._providers = {}
    audit_repo = FakeAuditRepository()
    gateway = ProviderGateway(
        FakeSessionRepository(sessions),
        AuditService(audit_repo),
        FakeTargetRepository(targets or []),
        operation_service,
    )
    return gateway, audit_repo


def _bound_power_target(
    *,
    target_id: str = "t1",
    capability_id: str = "cap-1",
    provider_key: str = "pdu-1",
    capability_type: str = "power",
    provider_config: dict[str, Any] | None = None,
    resource_type: str | None = None,
    agent_id: str = "agent-1",
    resource_id: str = "res-1",
):
    resource_family = {
        "power": "power",
        "reset": "power",
        "serial": "serial",
        "ssh": "network",
        "telnet": "network",
        "ftp": "network",
        "network": "network",
        "deploy": "deploy",
        "jlink": "debugger",
    }
    resolved_resource_type = resource_type or resource_family.get(capability_type, capability_type)
    agent = FakeAgent(id=agent_id)
    resource = FakeResource(id=resource_id, agent_id=agent_id, resource_type=resolved_resource_type)
    capability = FakeCapability(
        id=capability_id,
        capability_type=capability_type,
        provider_key=provider_key,
        provider_config=provider_config or {},
        agent_id=agent_id,
        resource_id=resource_id,
        agent=agent,
        resource=resource,
    )
    return FakeTarget(id=target_id, capabilities=[capability])


def test_power_operation_through_session_gateway_records_audit():
    session = FakeSession("s1", "user1", "t1", "power", "pdu-1")
    gateway, audit_repo = _gateway([session], [_bound_power_target()])

    result = gateway.execute("s1", "user1", "on")
    assert result["data"]["power"] == "on"
    assert any(e.action == "provider.execute" and e.operation == "on" for e in audit_repo.entries)


def test_non_owner_cannot_execute():
    session = FakeSession("s1", "user1", "t1", "power", "pdu-1")
    gateway, _ = _gateway([session], [_bound_power_target()])
    with pytest.raises(ConflictResource, match="owner"):
        gateway.execute("s1", "intruder", "on")


def test_expired_session_is_rejected():
    session = FakeSession(
        "s1", "user1", "t1", "power", "pdu-1",
        expires_at=datetime.now(UTC) - timedelta(minutes=1),
    )
    gateway, _ = _gateway([session], [_bound_power_target()])
    with pytest.raises(ConflictResource, match="expired"):
        gateway.execute("s1", "user1", "on")


def test_unsupported_operation_is_rejected():
    session = FakeSession("s1", "user1", "t1", "power", "pdu-1")
    gateway, _ = _gateway([session], [_bound_power_target()])
    with pytest.raises(ConflictResource, match="not supported"):
        gateway.execute("s1", "user1", "fly")


def test_missing_session_raises_not_found():
    gateway, _ = _gateway([], [])
    with pytest.raises(ResourceNotFound):
        gateway.execute("missing", "user1", "on")


def test_operations_listing_for_serial_session():
    session = FakeSession("s1", "user1", "t1", "serial", "serial-unset-key")
    target = _bound_power_target(
        capability_type="serial",
        provider_key="serial-unset-key",
    )
    gateway, _ = _gateway([session], [target])
    ops = gateway.operations_for("s1", "user1")
    assert "read" in ops["operations"]
    assert ops["capability_type"] == "serial"


def test_serial_read_autoopens_simulated_console():
    session = FakeSession("s1", "user1", "t1", "serial", "serial-unset-key")
    target = _bound_power_target(
        capability_type="serial",
        provider_key="serial-unset-key",
    )
    gateway, _ = _gateway([session], [target], FakeAgentOperationService())
    result = gateway.serial_read("s1", "user1")
    assert "console ready" in result["data"]["data_text"]


def test_serial_execute_requires_agent_operation_service():
    session = FakeSession("s1", "user1", "t1", "serial", "serial-unset-key")
    target = _bound_power_target(
        capability_type="serial",
        provider_key="serial-unset-key",
    )
    gateway, _ = _gateway([session], [target], None)
    with pytest.raises(ConflictResource, match="transport is not configured"):
        gateway.execute("s1", "user1", "open")


def test_session_binding_mismatch_is_rejected():
    session = FakeSession("s1", "user1", "t1", "power", "pdu-1", resource_id="res-x")
    gateway, _ = _gateway([session], [_bound_power_target(resource_id="res-1")])
    with pytest.raises(ConflictResource, match="binding"):
        gateway.execute("s1", "user1", "on")


def test_missing_session_binding_metadata_is_rejected():
    session = FakeSession("s1", "user1", "t1", "power", "pdu-1", capability_id=None)
    gateway, _ = _gateway([session], [_bound_power_target()])
    with pytest.raises(ConflictResource, match="missing capability binding"):
        gateway.execute("s1", "user1", "on")


def test_network_real_exec_through_gateway(monkeypatch):
    session = FakeSession("s1", "user1", "t1", "ssh", "net-1")
    target = _bound_power_target(
        capability_type="ssh",
        provider_key="net-1",
        provider_config={
            "mode": "real",
            "controller_url": "http://network.local",
            "channel_id": "lab-ssh",
            "allowed_commands": ["uname -a"],
        },
    )

    class _Response:
        def __init__(self, body: str):
            self.body = body.encode("utf-8")

        def read(self):
            return self.body

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    def _fake_urlopen(request, timeout=0, context=None):
        if str(request.full_url).endswith("/info"):
            return _Response('{"host":"10.0.0.7","port":22}')
        return _Response('{"output":"Linux","exit_code":0}')

    monkeypatch.setattr("urllib.request.urlopen", _fake_urlopen)

    gateway, _ = _gateway([session], [target])
    result = gateway.execute("s1", "user1", "exec", {"command": "uname -a"})
    assert result["operation"] == "exec"
    assert result["data"]["exit_code"] == 0


def test_deployment_real_timeout_through_gateway(monkeypatch):
    session = FakeSession("s1", "user1", "t1", "deploy", "dep-1")
    target = _bound_power_target(
        capability_type="deploy",
        provider_key="dep-1",
        provider_config={
            "mode": "real",
            "controller_url": "http://deploy.local",
            "target_id": "board-a",
            "timeout_seconds": 0.5,
        },
    )

    def _timeout(*_args, **_kwargs):
        raise TimeoutError("timed out")

    monkeypatch.setattr("urllib.request.urlopen", _timeout)

    gateway, _ = _gateway([session], [target])
    with pytest.raises(ConflictResource, match="timed out"):
        gateway.execute("s1", "user1", "status")


def test_debugger_real_auth_failure_through_gateway(monkeypatch):
    session = FakeSession("s1", "user1", "t1", "jlink", "dbg-1")
    target = _bound_power_target(
        capability_type="jlink",
        provider_key="dbg-1",
        provider_config={
            "mode": "real",
            "controller_url": "http://debug.local",
            "probe_id": "probe-a",
            "auth_type": "bearer",
            "bearer_token_env": "TARGETHUB_DEBUG_BEARER",
        },
    )

    # Do not define TARGETHUB_DEBUG_BEARER to verify auth failure handling.
    monkeypatch.delenv("TARGETHUB_DEBUG_BEARER", raising=False)
    gateway, _ = _gateway([session], [target])
    with pytest.raises(ConflictResource, match="token is missing"):
        gateway.execute("s1", "user1", "status")
