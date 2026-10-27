"""DD power driver (server-hosted and Agent fallback) against the mock DD server."""

from __future__ import annotations

import importlib.util
import sys
import threading
from pathlib import Path

import pytest

from app.core.config import settings
from app.providers.dd_power import DDPowerProvider, build_dd_config
from tests.helpers import api_client, auth, bootstrap, create_user, open_session, reserve

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "simulators"))
import dd_mock_server  # noqa: E402

MAC = "AA:BB:CC:DD:EE:FF"


@pytest.fixture
def dd():
    state = dd_mock_server.DDState(MAC, nodes=2, endpoints=4, confirm_delay=0.2, api_key="dd-secret")
    server = dd_mock_server.serve("127.0.0.1", 0, state, quiet=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield state, f"http://127.0.0.1:{server.server_port}"
    server.shutdown()


@pytest.fixture
def api_key(monkeypatch):
    monkeypatch.setenv("TARGETHUB_DD_KEY", "dd-secret")


def _provider(url, **overrides):
    cfg = {
        "driver": "dd", "base_url": url, "hub_mac": MAC, "node_id": 1, "endpoint": 2,
        "api_key_env": "TARGETHUB_DD_KEY", "cycle_delay_seconds": 0.5,
        "confirm_timeout_seconds": 3, "poll_interval_seconds": 0.05, **overrides,
    }
    return DDPowerProvider("dd-1", build_dd_config(cfg))


def test_on_waits_for_device_confirmation(dd, api_key):
    state, url = dd
    provider = _provider(url)
    assert provider.execute("status").data["state"] == "off"
    result = provider.execute("on")
    assert result.success and result.data["confirmed"] is True and result.data["power"] == "on"
    assert state.endpoints[(1, 2)]["current_state"] == "ON"


def test_unconfirmed_command_is_reported_honestly(dd, api_key):
    state, url = dd
    state.disconnected.add(1)  # device never confirms
    result = _provider(url, confirm_timeout_seconds=0.3).execute("on")
    assert result.success and result.data["confirmed"] is False
    assert "not confirmed" in result.message


def test_cycle_and_reset_are_off_then_on(dd, api_key):
    state, url = dd
    provider = _provider(url)
    provider.execute("on")
    result = provider.execute("reset")
    assert result.success and result.data["state"] == "on"
    assert [cmd["state"] for cmd in state.commands] == ["ON", "OFF", "ON"]


@pytest.mark.parametrize(
    ("setup", "expected"),
    [
        (lambda s: setattr(s, "emergency", True), "emergency lock"),
        (lambda s: setattr(s, "fail_next", 500), "failed to publish"),
    ],
)
def test_dd_errors_are_explained(dd, api_key, setup, expected):
    state, url = dd
    setup(state)
    result = _provider(url).execute("on")
    assert not result.success and expected in result.message


def test_wrong_api_key_and_unknown_endpoint(dd, monkeypatch):
    _state, url = dd
    monkeypatch.setenv("TARGETHUB_DD_KEY", "wrong")
    assert "API key" in _provider(url).execute("status").message
    monkeypatch.setenv("TARGETHUB_DD_KEY", "dd-secret")
    assert "not found" in _provider(url, endpoint=99).execute("status").message


def test_unreachable_dd_server():
    result = _provider("http://127.0.0.1:9", timeout_seconds=1).execute("status")
    assert not result.success and "unreachable" in result.message


@pytest.mark.parametrize(
    "bad",
    [
        {"base_url": "ftp://x"},
        {"hub_mac": "nope"},
        {"node_id": "x"},
        {"api_key": "inline-secret"},
        {"api_key_env": "lower-case"},
    ],
)
def test_config_validation(bad):
    cfg = {"driver": "dd", "base_url": "http://dd:5003", "hub_mac": MAC, "node_id": 1, "endpoint": 2, **bad}
    with pytest.raises(ValueError):
        build_dd_config(cfg)


def test_server_only_lab_without_agents(dd, api_key, tmp_path, monkeypatch):
    """A team with no Agents: reservations + DD power from the TargetHub server."""
    state, url = dd
    with api_client(tmp_path, monkeypatch) as (client, _db):
        admin = bootstrap(client)
        alice = create_user(client, admin, "alice")
        target = client.post(
            "/api/v1/targets",
            json={
                "name": "BOARD-DD",
                "capabilities": [
                    {
                        "name": "Power",
                        "capability_type": "power",
                        "provider_config": {
                            "driver": "dd", "base_url": url, "hub_mac": MAC, "node_id": 1, "endpoint": 3,
                            "api_key_env": "TARGETHUB_DD_KEY", "cycle_delay_seconds": 0.5,
                            "confirm_timeout_seconds": 3, "poll_interval_seconds": 0.05,
                        },
                    }
                ],
            },
            headers=auth(admin),
        )
        assert target.status_code == 201, target.text
        capability = client.get(f"/api/v1/targets/{target.json()['id']}", headers=auth(alice)).json()["capabilities"][0]
        assert capability["hosting"] == "server" and capability["mode"] == "dd"
        assert "provider_config" not in capability

        reservation = reserve(client, alice, target.json()["id"])
        session = open_session(client, alice, reservation["id"], "power")
        result = client.post(f"/api/v1/sessions/{session['id']}/execute", json={"operation": "cycle"}, headers=auth(alice))
        assert result.status_code == 200, result.text
        assert result.json()["data"]["power"] == "on"
        assert [cmd["state"] for cmd in state.commands] == ["OFF", "ON"]
        assert "dd-secret" not in result.text

        state.emergency = True
        locked = client.post(f"/api/v1/sessions/{session['id']}/execute", json={"operation": "off"}, headers=auth(alice))
        assert locked.status_code == 409 and "emergency lock" in locked.json()["detail"]


def test_simulated_power_is_refused_in_production(tmp_path, monkeypatch):
    with api_client(tmp_path, monkeypatch) as (client, _db):
        admin = bootstrap(client)
        monkeypatch.setattr(settings, "allow_simulated_providers", False)
        for config in ({}, {"driver": "simulated"}, {"mode": "simulated"}):
            response = client.post(
                "/api/v1/targets",
                json={"name": f"B-{len(config)}-{list(config)}", "capabilities": [
                    {"name": "Power", "capability_type": "power", "provider_config": config}]},
                headers=auth(admin),
            )
            assert response.status_code == 409, (config, response.text)
        monkeypatch.setattr(settings, "allow_simulated_providers", True)
        ok = client.post(
            "/api/v1/targets",
            json={"name": "DEMO", "capabilities": [
                {"name": "Power", "capability_type": "power", "provider_config": {"driver": "simulated"}}]},
            headers=auth(admin),
        )
        assert ok.status_code == 201 and ok.json()["capabilities"][0]["mode"] == "simulated"


def test_agent_dd_backend(dd):
    """Agent fallback when only the Agent host can reach the DD server."""
    _state, url = dd
    spec = importlib.util.spec_from_file_location(
        "agent_dd", ROOT / "backend" / "app" / "web" / "agent" / "targethub_agent.py"
    )
    agent = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(agent)
    metadata = {"backend": "dd", "base_url": url, "hub_mac": MAC, "node_id": 2, "endpoint": 1,
                "api_key": "dd-secret", "confirm_timeout": 3, "cycle_delay": 0.5}
    power = agent.PowerRuntime()
    assert power.execute("on", metadata)["data"]["confirmed"] is True
    assert power.execute("status", metadata)["data"]["state"] == "on"
    assert power.execute("cycle", metadata)["success"]
