"""Reservation policy, extend, reserve-any, calendar, maintenance, waitlist, notifications, webhooks."""

from __future__ import annotations

import hashlib
import hmac
import json
import threading
import time
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from app.models.reservation import Reservation
from app.services.scheduler import run_maintenance
from tests.helpers import api_client, auth, bootstrap, create_user, reserve


def _target(client, admin, name, tags=()):
    response = client.post("/api/v1/targets", json={"name": name, "tags": list(tags)}, headers=auth(admin))
    assert response.status_code == 201, response.text
    return response.json()


def _window(start_offset_min=0, minutes=30):
    start = datetime.now(UTC) + timedelta(minutes=start_offset_min)
    return start.isoformat(), (start + timedelta(minutes=minutes)).isoformat()


def _reserve_raw(client, token, target_id, start_offset_min=0, minutes=30):
    starts, ends = _window(start_offset_min, minutes)
    return client.post(
        "/api/v1/reservations",
        json={"target_id": target_id, "starts_at": starts, "ends_at": ends},
        headers=auth(token),
    )


def test_policy_limits_duration_advance_and_quota_but_not_admins(tmp_path, monkeypatch):
    with api_client(tmp_path, monkeypatch) as (client, _db):
        admin = bootstrap(client)
        alice = create_user(client, admin, "alice")
        policy = client.get("/api/v1/settings/policy", headers=auth(alice)).json()
        policy.update(max_duration_minutes=60, max_advance_days=1, max_active_reservations_per_user=1)
        assert client.put("/api/v1/settings/policy", json=policy, headers=auth(alice)).status_code == 403
        assert client.put("/api/v1/settings/policy", json=policy, headers=auth(admin)).status_code == 200

        b1, b2 = _target(client, admin, "B1"), _target(client, admin, "B2")
        too_long = _reserve_raw(client, alice, b1["id"], minutes=120)
        assert too_long.status_code == 409 and "60 minutes" in too_long.json()["detail"]
        too_far = _reserve_raw(client, alice, b1["id"], start_offset_min=3 * 24 * 60)
        assert too_far.status_code == 409 and "ahead" in too_far.json()["detail"]
        past = _reserve_raw(client, alice, b1["id"], start_offset_min=-60, minutes=90)
        assert past.status_code == 409 and "past" in past.json()["detail"]
        assert _reserve_raw(client, alice, b1["id"]).status_code == 201
        quota = _reserve_raw(client, alice, b2["id"])
        assert quota.status_code == 409 and "at most 1" in quota.json()["detail"]
        assert _reserve_raw(client, admin, b2["id"], minutes=600).status_code == 201


def test_extend_updates_reservation_and_sessions_and_respects_next_booking(tmp_path, monkeypatch):
    with api_client(tmp_path, monkeypatch) as (client, _db):
        admin = bootstrap(client)
        alice, bob = create_user(client, admin, "alice"), create_user(client, admin, "bob")
        board = _target(client, admin, "B1")
        mine = reserve(client, alice, board["id"], minutes=30)
        extended = client.post(f"/api/v1/reservations/{mine['id']}/extend", json={"extend_minutes": 15}, headers=auth(alice))
        assert extended.status_code == 200
        assert datetime.fromisoformat(extended.json()["ends_at"]) > datetime.fromisoformat(mine["ends_at"])

        assert _reserve_raw(client, bob, board["id"], start_offset_min=50, minutes=30).status_code == 201
        blocked = client.post(f"/api/v1/reservations/{mine['id']}/extend", json={"extend_minutes": 30}, headers=auth(alice))
        assert blocked.status_code == 409 and "bob" in blocked.json()["detail"]
        not_owner = client.post(f"/api/v1/reservations/{mine['id']}/extend", json={"extend_minutes": 1}, headers=auth(bob))
        assert not_owner.status_code == 409


def test_reserve_any_by_tag_picks_free_board(tmp_path, monkeypatch):
    with api_client(tmp_path, monkeypatch) as (client, _db):
        admin = bootstrap(client)
        alice, bob = create_user(client, admin, "alice"), create_user(client, admin, "bob")
        _target(client, admin, "N1", ["stm32-nucleo"])
        _target(client, admin, "N2", ["STM32-Nucleo", "lab-a"])
        _target(client, admin, "OTHER", ["esp32"])
        first = client.post("/api/v1/reservations/any", json={"tag": "stm32-nucleo", "duration_minutes": 30}, headers=auth(alice))
        second = client.post("/api/v1/reservations/any", json={"tag": "stm32-nucleo", "duration_minutes": 30}, headers=auth(bob))
        assert first.status_code == 201 and second.status_code == 201
        assert first.json()["target_id"] != second.json()["target_id"]
        third = client.post("/api/v1/reservations/any", json={"tag": "stm32-nucleo", "duration_minutes": 30}, headers=auth(admin))
        assert third.status_code == 409 and "busy" in third.json()["detail"]
        assert client.get("/api/v1/targets/tags", headers=auth(alice)).json() == ["esp32", "lab-a", "stm32-nucleo"]
        assert [t["name"] for t in client.get("/api/v1/targets?tag=esp32", headers=auth(alice)).json()] == ["OTHER"]


def test_availability_and_calendar_are_visible_to_everyone(tmp_path, monkeypatch):
    with api_client(tmp_path, monkeypatch) as (client, _db):
        admin = bootstrap(client)
        alice, bob = create_user(client, admin, "alice"), create_user(client, admin, "bob")
        board = _target(client, admin, "B1")
        reserve(client, alice, board["id"])
        listed = client.get("/api/v1/targets", headers=auth(bob)).json()
        assert listed[0]["availability"]["state"] == "reserved"
        assert listed[0]["availability"]["reserved_by"] == "alice"
        # Bob's own list is private, but the calendar shows everyone's bookings.
        assert client.get("/api/v1/reservations", headers=auth(bob)).json() == []
        calendar = client.get("/api/v1/reservations/calendar", headers=auth(bob)).json()
        assert [item["user_id"] for item in calendar] == ["alice"]


def test_maintenance_blocks_reservations_and_is_announced(tmp_path, monkeypatch):
    with api_client(tmp_path, monkeypatch) as (client, _db):
        admin = bootstrap(client)
        alice = create_user(client, admin, "alice")
        board = _target(client, admin, "B1")
        updated = client.put(
            f"/api/v1/targets/{board['id']}",
            json={"status": "maintenance", "status_reason": "USB hub broken"},
            headers=auth(admin),
        )
        assert updated.status_code == 200
        blocked = _reserve_raw(client, alice, board["id"])
        assert blocked.status_code == 409 and "USB hub broken" in blocked.json()["detail"]
        state = client.get(f"/api/v1/targets/{board['id']}", headers=auth(alice)).json()["availability"]
        assert state == {**state, "state": "maintenance", "reason": "USB hub broken"}
        back = client.put(f"/api/v1/targets/{board['id']}", json={"status": "available"}, headers=auth(admin)).json()
        assert back["status_reason"] is None
        bad = client.put(f"/api/v1/targets/{board['id']}", json={"status": "broken"}, headers=auth(admin))
        assert bad.status_code == 422


def test_waitlist_auto_reserves_when_target_is_released(tmp_path, monkeypatch):
    with api_client(tmp_path, monkeypatch) as (client, _db):
        admin = bootstrap(client)
        alice, bob = create_user(client, admin, "alice"), create_user(client, admin, "bob")
        board = _target(client, admin, "B1")
        held = reserve(client, alice, board["id"])
        joined = client.post("/api/v1/waitlist", json={"target_id": board["id"], "duration_minutes": 45}, headers=auth(bob))
        assert joined.status_code == 201 and joined.json()["status"] == "waiting" and joined.json()["position"] == 1
        duplicate = client.post("/api/v1/waitlist", json={"target_id": board["id"]}, headers=auth(bob))
        assert duplicate.status_code == 409

        client.post(f"/api/v1/reservations/{held['id']}/release", headers=auth(alice))
        mine = client.get("/api/v1/reservations", headers=auth(bob)).json()
        assert len(mine) == 1 and mine[0]["target_id"] == board["id"] and mine[0]["status"] == "active"
        entry = client.get("/api/v1/waitlist", headers=auth(bob)).json()
        assert entry == []  # no longer waiting
        inbox = client.get("/api/v1/notifications", headers=auth(bob)).json()
        assert inbox and inbox[0]["kind"] == "waitlist.fulfilled"
        assert client.post("/api/v1/notifications/read", headers=auth(bob)).json() == {"updated": 1}
        assert client.get("/api/v1/notifications?unread=true", headers=auth(bob)).json() == []


def test_waitlist_by_tag_and_leaving(tmp_path, monkeypatch):
    with api_client(tmp_path, monkeypatch) as (client, _db):
        admin = bootstrap(client)
        alice, bob = create_user(client, admin, "alice"), create_user(client, admin, "bob")
        board = _target(client, admin, "N1", ["nucleo"])
        held = reserve(client, alice, board["id"])
        entry = client.post("/api/v1/waitlist", json={"tag": "nucleo", "duration_minutes": 30}, headers=auth(bob)).json()
        assert client.delete(f"/api/v1/waitlist/{entry['id']}", headers=auth(alice)).status_code == 404
        assert client.delete(f"/api/v1/waitlist/{entry['id']}", headers=auth(bob)).json()["status"] == "cancelled"
        again = client.post("/api/v1/waitlist", json={"tag": "nucleo", "duration_minutes": 30}, headers=auth(bob)).json()
        assert again["status"] == "waiting"
        client.post(f"/api/v1/reservations/{held['id']}/release", headers=auth(alice))
        assert client.get("/api/v1/reservations", headers=auth(bob)).json()[0]["target_id"] == board["id"]


def test_scheduler_expires_warns_and_purges(tmp_path, monkeypatch):
    with api_client(tmp_path, monkeypatch) as (client, db_factory):
        admin = bootstrap(client)
        alice = create_user(client, admin, "alice")
        board = _target(client, admin, "B1")
        soon = reserve(client, alice, board["id"], minutes=5)
        with db_factory() as db:
            stats = run_maintenance(db)
            assert stats["expiry_warnings"] == 1
            assert run_maintenance(db)["expiry_warnings"] == 0  # once only
            reservation = db.get(Reservation, soon["id"])
            reservation.ends_at = datetime.now(UTC) - timedelta(seconds=1)
            db.commit()
            assert run_maintenance(db)["reservations_expired"] == 1
        kinds = [item["kind"] for item in client.get("/api/v1/notifications", headers=auth(alice)).json()]
        assert sorted(kinds) == ["reservation.expired", "reservation.expiring"]


class _Hook(BaseHTTPRequestHandler):
    received: list = []

    def do_POST(self):  # noqa: N802
        body = self.rfile.read(int(self.headers["Content-Length"]))
        _Hook.received.append((dict(self.headers), body))
        self.send_response(204)
        self.end_headers()

    def log_message(self, *_args):
        return


def test_webhooks_deliver_signed_events_and_hide_secrets(tmp_path, monkeypatch):
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Hook)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    _Hook.received = []
    try:
        with api_client(tmp_path, monkeypatch) as (client, _db):
            admin = bootstrap(client)
            alice = create_user(client, admin, "alice")
            url = f"http://127.0.0.1:{server.server_port}/hook"
            saved = client.put(
                "/api/v1/settings/webhooks",
                json={"webhooks": [{"name": "ci", "url": url, "events": ["reservation.created"], "secret": "s3cret"}]},
                headers=auth(admin),
            )
            assert saved.status_code == 200
            hook = saved.json()["webhooks"][0]
            assert hook["secret"] == "********"
            assert client.get("/api/v1/settings/webhooks", headers=auth(alice)).status_code == 403

            # Re-saving with the mask keeps the stored secret.
            client.put("/api/v1/settings/webhooks", json={"webhooks": [hook]}, headers=auth(admin))
            reserve(client, alice, _target(client, admin, "B1")["id"])
            deadline = time.monotonic() + 5
            while not _Hook.received and time.monotonic() < deadline:
                time.sleep(0.05)
            raw_headers, body = _Hook.received[0]
            headers = {key.lower(): value for key, value in raw_headers.items()}
            payload = json.loads(body)
            assert payload["event"] == "reservation.created" and payload["data"]["user_id"] == "alice"
            expected = hmac.new(b"s3cret", body, hashlib.sha256).hexdigest()
            assert headers["x-targethub-signature"] == f"sha256={expected}"

            assert client.post(f"/api/v1/settings/webhooks/{hook['id']}/test", headers=auth(admin)).status_code == 200
            bad = client.put(
                "/api/v1/settings/webhooks",
                json={"webhooks": [{"name": "x", "url": url, "events": ["nope"]}]},
                headers=auth(admin),
            )
            assert bad.status_code == 422
    finally:
        server.shutdown()


def test_api_timestamps_always_carry_utc_offset(tmp_path, monkeypatch):
    """SQLite drops offsets; clients must still receive unambiguous UTC times."""
    with api_client(tmp_path, monkeypatch) as (client, _db):
        admin = bootstrap(client)
        board = _target(client, admin, "B1")
        reservation = reserve(client, admin, board["id"])
        for value in (board["created_at"], reservation["starts_at"], reservation["ends_at"]):
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            assert parsed.utcoffset() == timedelta(0), value
        listed = client.get("/api/v1/reservations", headers=auth(admin)).json()[0]
        assert datetime.fromisoformat(listed["ends_at"].replace("Z", "+00:00")).tzinfo is not None
