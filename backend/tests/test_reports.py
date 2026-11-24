"""Usage reports: utilisation per board and tag, idle reservations, per-user hours and waitlist times."""

from __future__ import annotations

import csv
import io
import uuid
from datetime import UTC, datetime, timedelta

from app.models.lab import WaitlistEntry
from app.models.reservation import Reservation
from app.models.session import TargetSession
from tests.helpers import api_client, auth, bootstrap, create_user

NOW = datetime.now(UTC).replace(microsecond=0)
START = NOW - timedelta(days=10)


def _target(client, admin, name, tags=()):
    response = client.post("/api/v1/targets", json={"name": name, "tags": list(tags)}, headers=auth(admin))
    assert response.status_code == 201, response.text
    return response.json()


def _reservation(db, target_id, user, begin_hours_ago, hours, *, released_after=None, with_session=False,
                 status="released", note=None):
    starts = NOW - timedelta(hours=begin_hours_ago)
    ends = starts + timedelta(hours=hours)
    reservation = Reservation(
        id=str(uuid.uuid4()), target_id=target_id, user_id=user, starts_at=starts, ends_at=ends,
        status=status, note=note,
        released_at=starts + timedelta(hours=released_after) if released_after is not None else None,
    )
    db.add(reservation)
    db.flush()
    if with_session:
        db.add(TargetSession(id=str(uuid.uuid4()), reservation_id=reservation.id, target_id=target_id,
                             user_id=user, capability_type="serial", status="closed", expires_at=ends))
    db.commit()
    return reservation


def _by_name(rows, key, value):
    return next(row for row in rows if row[key] == value)


def _seed(client, session_local):
    admin = bootstrap(client)
    create_user(client, admin, "alice")
    create_user(client, admin, "bob")
    b1 = _target(client, admin, "B1", ["stm32", "rack-1"])
    b2 = _target(client, admin, "B2", ["stm32"])
    b3 = _target(client, admin, "B3-unused")
    with session_local() as db:
        _reservation(db, b1["id"], "alice", 100, 10, with_session=True)           # 10 h used
        _reservation(db, b1["id"], "bob", 50, 8, released_after=2)               # held 2 h, idle
        _reservation(db, b2["id"], "alice", 30, 4, with_session=True)            # 4 h used
        _reservation(db, b2["id"], "healthcheck", 20, 1, with_session=True)      # automation: ignored
        _reservation(db, b1["id"], "alice", 1000, 6, with_session=True)          # before the window
    return admin, b1, b2, b3


def test_utilisation_idle_and_per_user_hours(tmp_path, monkeypatch):
    with api_client(tmp_path, monkeypatch) as (client, session_local):
        admin, _b1, _b2, _b3 = _seed(client, session_local)
        report = client.get(
            "/api/v1/reports/usage", params={"from": START.isoformat(), "to": NOW.isoformat()}, headers=auth(admin)
        )
        assert report.status_code == 200, report.text
        body = report.json()
        assert body["period"]["hours"] == 240.0

        targets = body["targets"]
        b1 = _by_name(targets, "name", "B1")
        assert b1["reservations"] == 2 and b1["users"] == 2
        assert b1["booked_hours"] == 12.0  # 10 h + the 2 h bob actually held
        assert b1["utilisation_percent"] == 5.0
        assert b1["idle_reservations"] == 1 and b1["idle_hours"] == 2.0
        b2 = _by_name(targets, "name", "B2")
        assert b2["booked_hours"] == 4.0 and b2["reservations"] == 1  # health check not counted
        b3 = _by_name(targets, "name", "B3-unused")
        assert b3["reservations"] == 0 and b3["utilisation_percent"] == 0.0

        stm = _by_name(body["tags"], "tag", "stm32")
        assert stm["targets"] == 2 and stm["booked_hours"] == 16.0
        assert stm["utilisation_percent"] == round(16 / (240 * 2) * 100, 1)

        users = {row["user_id"]: row for row in body["users"]}
        assert users["alice"]["booked_hours"] == 14.0 and users["alice"]["idle_hours"] == 0.0
        assert users["bob"]["booked_hours"] == 2.0 and users["bob"]["idle_hours"] == 2.0
        assert "healthcheck" not in users
        assert body["users"][0]["user_id"] == "alice"  # sorted by hours

        assert [row["user_id"] for row in body["idle"]] == ["bob"] and body["idle"][0]["hours_held"] == 2.0
        totals = body["totals"]
        assert totals["booked_hours"] == 16.0 and totals["idle_hours"] == 2.0 and totals["idle_share_percent"] == 12.5


def test_reservations_are_clipped_to_the_period_and_running_ones_count_until_now(tmp_path, monkeypatch):
    with api_client(tmp_path, monkeypatch) as (client, session_local):
        admin = bootstrap(client)
        board = _target(client, admin, "CLIP")
        with session_local() as db:
            # 10 h long, 4 h of it before the period starts.
            _reservation(db, board["id"], "alice", 24 * 2 + 4, 10, with_session=True)
            # Still running: began 3 h ago, booked for 8 h, so only 3 h so far.
            _reservation(db, board["id"], "bob", 3, 8, status="active", with_session=True)
        start = NOW - timedelta(days=2)
        body = client.get(
            "/api/v1/reports/usage", params={"from": start.isoformat(), "to": NOW.isoformat()}, headers=auth(admin)
        ).json()
        assert _by_name(body["targets"], "name", "CLIP")["booked_hours"] == 6.0 + 3.0


def test_waitlist_summary_and_csv_exports(tmp_path, monkeypatch):
    with api_client(tmp_path, monkeypatch) as (client, session_local):
        admin, b1, _b2, _b3 = _seed(client, session_local)
        with session_local() as db:
            created = NOW - timedelta(days=1)
            db.add_all([
                WaitlistEntry(user_id="alice", target_id=b1["id"], duration_minutes=30, status="fulfilled",
                              created_at=created, fulfilled_at=created + timedelta(minutes=30)),
                WaitlistEntry(user_id="bob", tag="stm32", duration_minutes=30, status="fulfilled",
                              created_at=created, fulfilled_at=created + timedelta(minutes=90)),
                WaitlistEntry(user_id="alice", target_id=b1["id"], duration_minutes=30, status="expired", created_at=created),
            ])
            db.commit()
        params = {"from": START.isoformat(), "to": NOW.isoformat()}
        waitlist = client.get("/api/v1/reports/usage", params=params, headers=auth(admin)).json()["waitlist"]
        assert waitlist["entries"] == 3 and waitlist["fulfilled"] == 2 and waitlist["expired"] == 1
        assert waitlist["average_wait_minutes"] == 60.0 and waitlist["longest_wait_minutes"] == 90.0

        response = client.get("/api/v1/reports/usage.csv", params={**params, "kind": "waitlist"}, headers=auth(admin))
        assert response.status_code == 200 and response.headers["content-type"].startswith("text/csv")
        assert "attachment" in response.headers["content-disposition"]
        rows = list(csv.DictReader(io.StringIO(response.text)))
        assert len(rows) == 3 and {row["status"] for row in rows} == {"fulfilled", "expired"}

        targets_csv = client.get("/api/v1/reports/usage.csv", params=params, headers=auth(admin))
        parsed = {row["name"]: row for row in csv.DictReader(io.StringIO(targets_csv.text))}
        assert parsed["B1"]["booked_hours"] == "12.0" and parsed["B1"]["tags"] == "stm32;rack-1"


def test_csv_neutralises_spreadsheet_formulas(tmp_path, monkeypatch):
    with api_client(tmp_path, monkeypatch) as (client, session_local):
        admin = bootstrap(client)
        board = _target(client, admin, "=HYPERLINK(\"http://evil\")")
        with session_local() as db:
            _reservation(db, board["id"], "alice", 5, 2, released_after=1, note="=cmd|' /C calc'!A0")
        params = {"from": START.isoformat(), "to": NOW.isoformat()}
        text = client.get("/api/v1/reports/usage.csv", params={**params, "kind": "idle"}, headers=auth(admin)).text
        rows = list(csv.DictReader(io.StringIO(text)))
        assert rows[0]["target"].startswith("'=") and rows[0]["note"].startswith("'=")


def test_reports_are_admin_only_and_validate_the_period(tmp_path, monkeypatch):
    with api_client(tmp_path, monkeypatch) as (client, _db):
        admin = bootstrap(client)
        alice = create_user(client, admin, "alice")
        viewer = create_user(client, admin, "vera", roles=["viewer"])
        for token in (alice, viewer):
            assert client.get("/api/v1/reports/usage", headers=auth(token)).status_code == 403
            assert client.get("/api/v1/reports/usage.csv", headers=auth(token)).status_code == 403
        assert client.get("/api/v1/reports/usage").status_code == 401
        default = client.get("/api/v1/reports/usage", headers=auth(admin))
        assert default.status_code == 200 and default.json()["period"]["hours"] == 720.0
        backwards = client.get(
            "/api/v1/reports/usage", params={"from": NOW.isoformat(), "to": START.isoformat()}, headers=auth(admin)
        )
        assert backwards.status_code == 422
        too_long = client.get(
            "/api/v1/reports/usage", params={"from": (NOW - timedelta(days=400)).isoformat()}, headers=auth(admin)
        )
        assert too_long.status_code == 422
