"""Board health checks: power the board, expect a boot banner, quarantine boards that stay silent."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.models.health_check import HealthCheck
from app.models.reservation import Reservation
from app.models.target import Target
from app.services.health_check_service import claim_due
from tests.helpers import (
    FakeAgent,
    agent_target,
    api_client,
    auth,
    bootstrap,
    create_user,
    enroll_agent,
    heartbeat,
    reserve,
)

SERIAL = {"resource_key": "sim://uart0", "resource_type": "serial", "display_name": "uart0", "metadata": {"simulated": True}}
POWER = {"resource_key": "power:relay1", "resource_type": "power", "display_name": "relay", "metadata": {}}
BANNER = "U-Boot 2026.01\nlogin: "


class Board:
    """What the fake agent plays: silent until powered, then prints the banner (unless broken)."""

    def __init__(self, works: bool = True):
        self.works = works
        self.powered = False

    def __call__(self, operation: dict) -> dict:
        name = operation["operation"]
        if name in {"cycle", "reset", "on"}:
            self.powered = True
            return {"success": True, "message": f"{name} done", "data": {"state": "on"}}
        if name == "read":
            text = BANNER if (self.powered and self.works) else ""
            self.powered = self.powered and not self.works
            return {"success": True, "message": "ok", "data": {"data_text": text, "bytes_read": len(text)}}
        return {"success": True, "message": f"{name} ok", "data": {}}


def _lab(client, with_serial=True):
    admin = bootstrap(client)
    agent_id, credential = enroll_agent(client, admin)
    ids = heartbeat(client, agent_id, credential, [SERIAL, POWER])
    capabilities = [{"name": "Relay", "capability_type": "power", "agent_id": agent_id, "resource_id": ids["power:relay1"]}]
    if with_serial:
        capabilities.append(
            {"name": "Console", "capability_type": "serial", "agent_id": agent_id, "resource_id": ids["sim://uart0"]}
        )
    target = agent_target(client, admin, "BOARD-HC", capabilities)
    return admin, agent_id, credential, target


CONFIG = {"enabled": True, "boot_pattern": "login:", "boot_timeout_seconds": 10, "failure_threshold": 2}


def _fast_timeout(session_local, target_id, seconds=1):
    with session_local() as db:
        db.get(HealthCheck, target_id).boot_timeout_seconds = seconds
        db.commit()


def _run(client, admin, target_id):
    response = client.post(f"/api/v1/targets/{target_id}/health-check/run", headers=auth(admin))
    assert response.status_code == 200, response.text
    return response.json()


def test_config_is_admin_only_validated_and_removable(tmp_path, monkeypatch):
    with api_client(tmp_path, monkeypatch) as (client, _db):
        admin, _agent, _cred, target = _lab(client)
        alice = create_user(client, admin, "alice")
        url = f"/api/v1/targets/{target['id']}/health-check"
        assert client.get(url, headers=auth(admin)).status_code == 404
        assert client.put(url, json=CONFIG, headers=auth(alice)).status_code == 403
        assert client.put(url, json={**CONFIG, "boot_timeout_seconds": 1}, headers=auth(admin)).status_code == 422
        assert client.put(url, json={**CONFIG, "power_operation": "off"}, headers=auth(admin)).status_code == 422
        saved = client.put(url, json=CONFIG, headers=auth(admin))
        assert saved.status_code == 200, saved.text
        body = saved.json()
        assert body["boot_pattern"] == "login:" and body["next_run_at"] is not None and body["last_status"] is None
        assert client.put("/api/v1/targets/does-not-exist/health-check", json=CONFIG, headers=auth(admin)).status_code == 404
        disabled = client.put(url, json={**CONFIG, "enabled": False}, headers=auth(admin)).json()
        assert disabled["next_run_at"] is None
        assert client.delete(url, headers=auth(admin)).status_code == 204
        assert client.get(url, headers=auth(admin)).status_code == 404


def test_passing_check_releases_board_and_records_result(tmp_path, monkeypatch):
    with api_client(tmp_path, monkeypatch) as (client, session_local):
        admin, agent_id, credential, target = _lab(client)
        url = f"/api/v1/targets/{target['id']}/health-check"
        client.put(url, json=CONFIG, headers=auth(admin))
        with FakeAgent(client, agent_id, credential, Board(works=True)) as agent:
            result = _run(client, admin, target["id"])
        assert result["status"] == "passed", result
        assert {op["operation"] for op in agent.seen} >= {"open", "read", "cycle"}

        with session_local() as db:
            reservations = db.scalars(select(Reservation).where(Reservation.target_id == target["id"])).all()
            assert [r.status for r in reservations] == ["released"] and reservations[0].user_id == "healthcheck"
            assert db.get(Target, target["id"]).status == "available"
        state = client.get(url, headers=auth(admin)).json()
        assert state["last_status"] == "passed" and state["consecutive_failures"] == 0
        results = client.get(f"{url}/results", headers=auth(admin)).json()
        assert results[0]["status"] == "passed" and results[0]["trigger"] == "manual"
        # The board is bookable again straight away.
        assert reserve(client, admin, target["id"])["status"] == "active"


def test_repeated_failures_put_board_in_maintenance_and_a_pass_restores_it(tmp_path, monkeypatch):
    with api_client(tmp_path, monkeypatch) as (client, session_local):
        admin, agent_id, credential, target = _lab(client)
        url = f"/api/v1/targets/{target['id']}/health-check"
        client.put(url, json=CONFIG, headers=auth(admin))
        _fast_timeout(session_local, target["id"])
        board = Board(works=False)
        with FakeAgent(client, agent_id, credential, board):
            first = _run(client, admin, target["id"])
            assert first["status"] == "failed" and "login:" in first["message"]
            with session_local() as db:
                assert db.get(Target, target["id"]).status == "available"  # one failure is not enough

            second = _run(client, admin, target["id"])
            assert second["status"] == "failed"
            with session_local() as db:
                quarantined = db.get(Target, target["id"])
                assert quarantined.status == "maintenance"
                assert quarantined.status_reason.startswith("Health check failed")
                assert db.get(HealthCheck, target["id"]).maintenance_by_check is True
            assert client.post(
                "/api/v1/reservations",
                json={"target_id": target["id"], "starts_at": datetime.now(UTC).isoformat(),
                      "ends_at": (datetime.now(UTC) + timedelta(minutes=10)).isoformat()},
                headers=auth(admin),
            ).status_code == 409

            board.works = True  # the board has been repaired
            third = _run(client, admin, target["id"])
            assert third["status"] == "passed", third
        with session_local() as db:
            restored = db.get(Target, target["id"])
            assert restored.status == "available" and restored.status_reason is None
            assert db.get(HealthCheck, target["id"]).consecutive_failures == 0
            assert all(r.status == "released" for r in db.scalars(select(Reservation)).all())


def test_check_is_skipped_not_failed_when_board_is_in_use_or_incomplete(tmp_path, monkeypatch):
    with api_client(tmp_path, monkeypatch) as (client, session_local):
        admin, _agent, _cred, target = _lab(client)
        url = f"/api/v1/targets/{target['id']}/health-check"
        client.put(url, json=CONFIG, headers=auth(admin))
        alice = create_user(client, admin, "alice")
        reserve(client, alice, target["id"])
        busy = _run(client, admin, target["id"])
        assert busy["status"] == "skipped" and "alice" in busy["message"]
        state = client.get(url, headers=auth(admin)).json()
        assert state["last_status"] == "skipped" and state["consecutive_failures"] == 0

        other_admin, _a, _c, no_serial = _lab_without_serial(client, admin)
        client.put(f"/api/v1/targets/{no_serial['id']}/health-check", json=CONFIG, headers=auth(admin))
        incomplete = _run(client, admin, no_serial["id"])
        assert incomplete["status"] == "skipped" and "serial" in incomplete["message"]


def _lab_without_serial(client, admin):
    agent_id, credential = enroll_agent(client, admin, name="agent-2")
    ids = heartbeat(client, agent_id, credential, [POWER])
    target = agent_target(
        client,
        admin,
        "BOARD-NOSERIAL",
        [{"name": "Relay", "capability_type": "power", "agent_id": agent_id, "resource_id": ids["power:relay1"]}],
    )
    return admin, agent_id, credential, target


def test_scheduler_claims_each_due_check_once(tmp_path, monkeypatch):
    with api_client(tmp_path, monkeypatch) as (client, session_local):
        admin, _agent, _cred, target = _lab(client)
        client.put(f"/api/v1/targets/{target['id']}/health-check", json=CONFIG, headers=auth(admin))
        with session_local() as db:
            now = datetime.now(UTC)
            assert claim_due(db, now) == [target["id"]]
            assert claim_due(db, now) == []  # claimed: another worker does not repeat it
            cfg = db.get(HealthCheck, target["id"])
            assert cfg.next_run_at is not None
            future = now + timedelta(hours=1)
            assert claim_due(db, future) == [target["id"]]  # an abandoned claim expires

        client.put(
            f"/api/v1/targets/{target['id']}/health-check", json={**CONFIG, "enabled": False}, headers=auth(admin)
        )
        with session_local() as db:
            assert claim_due(db, datetime.now(UTC) + timedelta(days=2)) == []


def test_failing_checks_show_up_in_the_admin_overview(tmp_path, monkeypatch):
    with api_client(tmp_path, monkeypatch) as (client, session_local):
        admin, agent_id, credential, target = _lab(client)
        client.put(f"/api/v1/targets/{target['id']}/health-check", json=CONFIG, headers=auth(admin))
        _fast_timeout(session_local, target["id"])
        assert [i for i in client.get("/api/v1/system/overview", headers=auth(admin)).json()["issues"]
                if "health check" in i["message"]] == []
        with FakeAgent(client, agent_id, credential, Board(works=False)):
            _run(client, admin, target["id"])
            warning = [i for i in client.get("/api/v1/system/overview", headers=auth(admin)).json()["issues"]
                       if "health check" in i["message"]]
            assert len(warning) == 1 and warning[0]["severity"] == "warning"
            _run(client, admin, target["id"])
        error = [i for i in client.get("/api/v1/system/overview", headers=auth(admin)).json()["issues"]
                 if "health check" in i["message"]]
        assert len(error) == 1 and error[0]["severity"] == "error" and "maintenance" in error[0]["message"]
