"""Third-party provider plugins."""

from __future__ import annotations

import sys
import types

import pytest

from app.providers import plugins
from app.providers.base import ProviderOperationResult, TargetProvider
from tests.helpers import api_client, auth, bootstrap, create_user, open_session, reserve


class SwitchProvider(TargetProvider):
    capability_type = "power"

    def __init__(self, provider_key, host):
        self.provider_key = provider_key
        self.host = host
        self.on = False

    def health_check(self):
        return ProviderOperationResult(True, "ok", {"host": self.host})

    def operations(self):
        return ["health", "status", "on", "off"]

    def execute(self, operation, params=None):
        if operation in {"on", "off"}:
            self.on = operation == "on"
        if operation in {"on", "off", "status"}:
            return ProviderOperationResult(True, f"switch is {'on' if self.on else 'off'}", {"state": "on" if self.on else "off"})
        return super().execute(operation, params)


class SwitchPlugin:
    name = "fakeswitch"
    capability_types = ("power", "reset")

    def validate(self, provider_key, provider_config):
        if not provider_config.get("host"):
            raise ValueError("fakeswitch needs 'host'")

    def build(self, provider_key, provider_config):
        return SwitchProvider(provider_key, provider_config["host"])


@pytest.fixture(autouse=True)
def clean_plugins():
    plugins.reset_for_tests()
    yield
    plugins.reset_for_tests()


def _power_target(client, admin, config):
    return client.post(
        "/api/v1/targets",
        json={"name": "SWITCHED", "capabilities": [
            {"name": "Supply", "capability_type": "power", "provider_config": config}
        ]},
        headers=auth(admin),
    )


def test_plugin_provides_a_power_driver_end_to_end(tmp_path, monkeypatch):
    plugins.register(SwitchPlugin())
    with api_client(tmp_path, monkeypatch) as (client, _db):
        admin = bootstrap(client)
        alice = create_user(client, admin, "alice")
        created = _power_target(client, admin, {"driver": "fakeswitch", "host": "10.0.0.7"})
        assert created.status_code == 201, created.text
        assert created.json()["capabilities"][0]["mode"] == "plugin"
        reservation = reserve(client, alice, created.json()["id"])
        session = open_session(client, alice, reservation["id"], "power")
        url = f"/api/v1/sessions/{session['id']}/execute"
        assert client.post(url, json={"operation": "on", "params": {}}, headers=auth(alice)).json()["data"]["state"] == "on"
        status = client.post(url, json={"operation": "status", "params": {}}, headers=auth(alice)).json()
        assert status["message"] == "switch is on"


def test_plugin_validation_errors_reach_the_admin(tmp_path, monkeypatch):
    plugins.register(SwitchPlugin())
    with api_client(tmp_path, monkeypatch) as (client, _db):
        admin = bootstrap(client)
        response = _power_target(client, admin, {"driver": "fakeswitch"})
        assert response.status_code in (409, 422) and "needs 'host'" in response.text
        unknown = _power_target(client, admin, {"driver": "nonexistent", "host": "x"})
        assert unknown.status_code in (409, 422)


def test_plugins_load_from_the_environment_and_bad_ones_are_skipped(monkeypatch):
    module = types.ModuleType("my_lab_plugins")
    module.SWITCH = SwitchPlugin()
    module.BROKEN = object()
    monkeypatch.setitem(sys.modules, "my_lab_plugins", module)
    monkeypatch.setenv(plugins.ENV_VAR, "my_lab_plugins:SWITCH, my_lab_plugins:BROKEN, no_such_module:X, bad-spec")
    info = plugins.describe()
    assert [item["name"] for item in info["plugins"]] == ["fakeswitch"]
    assert len(info["errors"]) == 3
    assert plugins.find("power", "FakeSwitch") is not None
    assert plugins.find("serial", "fakeswitch") is None  # not declared for serial


def test_plugin_contract_is_enforced():
    class NoName:
        capability_types = ("power",)

        def validate(self, *_a): ...

        def build(self, *_a): ...

    with pytest.raises(ValueError, match="name"):
        plugins.register(NoName())

    class Reserved(SwitchPlugin):
        name = "http"

    with pytest.raises(ValueError, match="built-in"):
        plugins.register(Reserved())

    class WrongType(SwitchPlugin):
        name = "weird"
        capability_types = ("toaster",)

    with pytest.raises(ValueError, match="unknown capability"):
        plugins.register(WrongType())

    plugins.register(SwitchPlugin())
    with pytest.raises(ValueError, match="already registered"):
        plugins.register(SwitchPlugin())


def test_plugin_that_returns_the_wrong_type_is_rejected():
    class Liar(SwitchPlugin):
        name = "liar"

        def build(self, *_a):
            return object()

    info = plugins.register(Liar())
    with pytest.raises(ValueError, match="TargetProvider"):
        plugins.build(info, "k", {})


def test_plugin_list_is_admin_only(tmp_path, monkeypatch):
    plugins.register(SwitchPlugin())
    with api_client(tmp_path, monkeypatch) as (client, _db):
        admin = bootstrap(client)
        alice = create_user(client, admin, "alice")
        assert client.get("/api/v1/providers/plugins", headers=auth(alice)).status_code == 403
        body = client.get("/api/v1/providers/plugins", headers=auth(admin)).json()
        assert body["plugins"][0]["name"] == "fakeswitch" and body["errors"] == []
