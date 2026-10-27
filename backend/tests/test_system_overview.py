"""Admin system overview (counts, configuration issues) and the DD power check."""

from __future__ import annotations

import sys
import threading
from pathlib import Path

import pytest

from tests.helpers import api_client, auth, bootstrap, create_user, enroll_agent, heartbeat

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "simulators"))
import dd_mock_server  # noqa: E402

MAC = "AA:BB:CC:DD:EE:FF"


@pytest.fixture
def dd():
    state = dd_mock_server.DDState(MAC, nodes=1, endpoints=2, confirm_delay=0.05, api_key="k")
    server = dd_mock_server.serve("127.0.0.1", 0, state, quiet=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()


def dd_config(url, env="TH_TEST_DD_KEY"):
    return {"driver": "dd", "base_url": url, "hub_mac": MAC, "node_id": 1, "endpoint": 1, "api_key_env": env}


def test_overview_counts_and_flags_misconfiguration(tmp_path, monkeypatch, dd):
    monkeypatch.delenv("TH_MISSING_KEY", raising=False)
    with api_client(tmp_path, monkeypatch) as (client, _db):
        admin = bootstrap(client)
        user = create_user(client, admin, "alice")
        agent_id, credential = enroll_agent(client, admin, "pi-1")
        resources = heartbeat(client, agent_id, credential, [
            {"resource_key": "/dev/ttyUSB0", "resource_type": "serial", "display_name": "uart", "metadata": {}}])
        response = client.post("/api/v1/targets", headers=auth(admin), json={
            "name": "B1", "capabilities": [
                {"name": "Console", "capability_type": "serial", "agent_id": agent_id,
                 "resource_id": resources["/dev/ttyUSB0"]},
                {"name": "Power", "capability_type": "power", "provider_config": dd_config(dd, "TH_MISSING_KEY")},
            ]})
        assert response.status_code == 201, response.text

        assert client.get("/api/v1/system/overview", headers=auth(user)).status_code == 403
        data = client.get("/api/v1/system/overview", headers=auth(admin)).json()
        assert data["targets"]["total"] == 1 and data["users"]["total"] == 2
        assert data["agents"] == {"total": 1, "online": 1, "disabled": 0}
        messages = [issue["message"] for issue in data["issues"]]
        assert any("TH_MISSING_KEY" in m and "B1 · Power" in m for m in messages), messages

        client.post(f"/api/v1/agents/{agent_id}/disable", headers=auth(admin))
        messages = [i["message"] for i in client.get("/api/v1/system/overview", headers=auth(admin)).json()["issues"]]
        assert any("is disabled" in m for m in messages), messages


def test_power_check_reports_dd_status_and_errors(tmp_path, monkeypatch, dd):
    monkeypatch.setenv("TH_TEST_DD_KEY", "k")
    with api_client(tmp_path, monkeypatch) as (client, _db):
        admin = bootstrap(client)
        ok = client.post("/api/v1/system/power-check", headers=auth(admin),
                         json={"provider_config": dd_config(dd)}).json()
        assert ok["success"] is True and ok["data"]["state"] == "off"

        monkeypatch.setenv("TH_TEST_DD_KEY", "wrong")
        bad = client.post("/api/v1/system/power-check", headers=auth(admin),
                          json={"provider_config": dd_config(dd)}).json()
        assert bad["success"] is False and "API key" in bad["message"]

        invalid = client.post("/api/v1/system/power-check", headers=auth(admin),
                              json={"provider_config": {**dd_config(dd), "hub_mac": "nope"}}).json()
        assert invalid["success"] is False and invalid["message"].startswith("Invalid configuration")
