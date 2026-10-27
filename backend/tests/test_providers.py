import os
import urllib.error
from typing import Any

os.environ.setdefault("SECRET_KEY", "test-secret-key")

import pytest
from app.providers import registry
from app.providers.debugger import DebuggerProvider, build_debugger_provider_config
from app.providers.deployment import DeploymentProvider, build_deployment_provider_config
from app.providers.network import NetworkProvider, build_network_provider_config
from app.providers.power import PowerProvider, PowerProviderConfig
from app.providers.serial import SimulatedSerialProvider


class _FakeHTTPResponse:
    def __init__(self, payload: dict[str, Any]):
        import json

        self._body = json.dumps(payload).encode("utf-8")

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def test_registry_maps_capabilities_to_providers():
    assert registry.is_supported("serial")
    assert registry.is_supported("power")
    assert registry.is_supported("ssh")
    assert registry.is_supported("jlink")
    assert registry.is_supported("deploy")
    assert not registry.is_supported("unknown")


def test_serial_without_config_is_simulated():
    provider = registry.build_provider("serial", "serial-unconfigured-key")
    assert isinstance(provider, SimulatedSerialProvider)


def test_power_provider_state_machine():
    provider = PowerProvider(PowerProviderConfig(provider_key="pdu-test-1"))
    assert provider.execute("off").data["power"] == "off"
    assert provider.execute("on").data["power"] == "on"
    assert provider.execute("status").data["power"] == "on"
    assert provider.execute("cycle").data["power"] == "on"


def test_debugger_requires_attach_before_core_ops():
    provider = DebuggerProvider(build_debugger_provider_config("jlink-test-1", {}))
    blocked = provider.execute("halt")
    assert blocked.success is False
    assert provider.execute("attach").success is True
    assert provider.execute("halt").data["core"] == "halted"
    assert provider.execute("resume").data["core"] == "running"


def test_deployment_records_last_artifact():
    provider = DeploymentProvider(build_deployment_provider_config("deploy-test-1", {}))
    result = provider.execute("deploy", {"artifact": "app.bin"})
    assert result.success is True
    assert result.data["artifact"] == "app.bin"
    status = provider.execute("status")
    assert status.data["artifact"] == "app.bin"


def test_network_exec_returns_output():
    provider = NetworkProvider(build_network_provider_config("ssh-test-1", "ssh", {}))
    info = provider.execute("info")
    assert info.data["protocol"] == "ssh"
    result = provider.execute("exec", {"command": "uname -a"})
    assert result.success is True
    assert result.data["exit_code"] == 0


def test_simulated_serial_echo_roundtrip():
    provider = SimulatedSerialProvider("serial-sim-1")
    assert provider.execute("open").success is True
    provider.execute("write", {"text": "hello"})
    read = provider.execute("read")
    assert b"hello" in read.data["data"]


def test_network_real_exec_uses_allowed_commands(monkeypatch):
    config = build_network_provider_config(
        "ssh-real-1",
        "ssh",
        {
            "mode": "real",
            "controller_url": "http://network.local",
            "channel_id": "lab-ssh",
            "allowed_commands": ["uname -a"],
        },
    )
    provider = NetworkProvider(config)

    def _fake_urlopen(request, timeout=0, context=None):
        if str(request.full_url).endswith("/info"):
            return _FakeHTTPResponse({"host": "10.0.0.7", "port": 22})
        return _FakeHTTPResponse({"output": "Linux", "exit_code": 0})

    monkeypatch.setattr("urllib.request.urlopen", _fake_urlopen)

    info = provider.execute("info")
    assert info.success is True
    assert info.data["host"] == "10.0.0.7"

    executed = provider.execute("exec", {"command": "uname -a"})
    assert executed.success is True
    assert executed.data["exit_code"] == 0


def test_network_real_exec_rejects_non_allowlisted_command():
    config = build_network_provider_config(
        "ssh-real-2",
        "ssh",
        {
            "mode": "real",
            "controller_url": "http://network.local",
            "channel_id": "lab-ssh",
            "allowed_commands": ["uname -a"],
        },
    )
    provider = NetworkProvider(config)
    denied = provider.execute("exec", {"command": "rm -rf /"})
    assert denied.success is False
    assert "allowed_commands" in denied.message


def test_deployment_real_rejects_unsafe_artifact_path():
    provider = DeploymentProvider(
        build_deployment_provider_config(
            "deploy-real-1",
            {
                "mode": "real",
                "controller_url": "http://deploy.local",
                "target_id": "board-a",
            },
        )
    )
    result = provider.execute("deploy", {"artifact": "../secret.bin", "bytes": 42})
    assert result.success is False
    assert "must not contain '..'" in result.message


def test_deployment_real_reports_timeout(monkeypatch):
    provider = DeploymentProvider(
        build_deployment_provider_config(
            "deploy-real-2",
            {
                "mode": "real",
                "controller_url": "http://deploy.local",
                "target_id": "board-a",
                "timeout_seconds": 0.5,
            },
        )
    )

    def _timeout(*_args, **_kwargs):
        raise TimeoutError("timed out")

    monkeypatch.setattr("urllib.request.urlopen", _timeout)
    result = provider.execute("status")
    assert result.success is False
    assert "timed out" in result.message.lower()


def test_debugger_real_actions_flow(monkeypatch):
    provider = DebuggerProvider(
        build_debugger_provider_config(
            "jlink-real-1",
            {
                "mode": "real",
                "controller_url": "http://debug.local",
                "probe_id": "probe-a",
            },
        )
    )

    def _fake_urlopen(request, timeout=0, context=None):
        if str(request.full_url).endswith("/status"):
            return _FakeHTTPResponse({"attached": False, "core": "running"})
        if str(request.full_url).endswith("/attach"):
            return _FakeHTTPResponse({"attached": True, "core": "running"})
        if str(request.full_url).endswith("/halt"):
            return _FakeHTTPResponse({"attached": True, "core": "halted"})
        return _FakeHTTPResponse({"attached": True, "core": "running"})

    monkeypatch.setattr("urllib.request.urlopen", _fake_urlopen)

    status = provider.execute("status")
    assert status.success is True
    attach = provider.execute("attach")
    assert attach.success is True
    halt = provider.execute("halt")
    assert halt.success is True
    assert halt.data["core"] == "halted"


def test_power_real_reports_unreachable_controller(monkeypatch):
    provider = registry.build_provider(
        "power",
        "pdu-real-1",
        {
            "mode": "real",
            "controller_url": "http://power.local",
            "outlet_id": "outlet-1",
        },
    )

    def _unreachable(*_args, **_kwargs):
        raise urllib.error.URLError("no route")

    monkeypatch.setattr("urllib.request.urlopen", _unreachable)
    result = provider.execute("status")
    assert result.success is False
    assert "unreachable" in result.message.lower()


def test_registry_validates_all_real_provider_configs():
    with pytest.raises(ValueError, match="controller_url"):
        registry.validate_provider_config("ssh", "net-a", {"mode": "real"})
    with pytest.raises(ValueError, match="target_id"):
        registry.validate_provider_config("deploy", "dep-a", {"mode": "real", "controller_url": "http://x"})
    with pytest.raises(ValueError, match="probe_id"):
        registry.validate_provider_config("jlink", "dbg-a", {"mode": "real", "controller_url": "http://x"})


def test_network_real_recovers_after_transient_unreachable(monkeypatch):
    config = build_network_provider_config(
        "ssh-real-3",
        "ssh",
        {
            "mode": "real",
            "controller_url": "http://network.local",
            "channel_id": "lab-ssh",
            "allowed_commands": ["uname -a"],
        },
    )
    provider = NetworkProvider(config)
    calls = {"count": 0}

    def _flaky_urlopen(request, timeout=0, context=None):
        calls["count"] += 1
        if calls["count"] == 1:
            raise urllib.error.URLError("temporarily unreachable")
        return _FakeHTTPResponse({"output": "Linux", "exit_code": 0})

    monkeypatch.setattr("urllib.request.urlopen", _flaky_urlopen)

    first = provider.execute("exec", {"command": "uname -a"})
    second = provider.execute("exec", {"command": "uname -a"})

    assert first.success is False
    assert "unreachable" in first.message.lower()
    assert second.success is True
    assert second.data["exit_code"] == 0
