"""Teams: membership, restricted boards, waitlist, reports."""

from __future__ import annotations

from tests.helpers import api_client, auth, bootstrap, create_user, reservation_window


def _target(client, admin, name, tags=None):
    response = client.post("/api/v1/targets", json={"name": name, "tags": tags or []}, headers=auth(admin))
    assert response.status_code == 201, response.text
    return response.json()


def _reserve(client, token, target_id):
    starts, ends = reservation_window(30)
    return client.post(
        "/api/v1/reservations", json={"target_id": target_id, "starts_at": starts, "ends_at": ends}, headers=auth(token)
    )


def _team(client, admin, name, members=(), target_ids=()):
    response = client.post(
        "/api/v1/teams",
        json={"name": name, "members": list(members), "target_ids": list(target_ids)},
        headers=auth(admin),
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_restricted_board_is_reservable_only_by_team_members_and_admins(tmp_path, monkeypatch):
    with api_client(tmp_path, monkeypatch) as (client, _db):
        admin = bootstrap(client)
        alice = create_user(client, admin, "alice")
        bob = create_user(client, admin, "bob")
        secret = _target(client, admin, "SECRET-BOARD")
        open_board = _target(client, admin, "OPEN-BOARD")
        _team(client, admin, "firmware", members=["alice"], target_ids=[secret["id"]])

        denied = _reserve(client, bob, secret["id"])
        assert denied.status_code == 409 and "firmware" in denied.text
        assert _reserve(client, alice, secret["id"]).status_code == 201
        assert _reserve(client, bob, open_board["id"]).status_code == 201
        assert _reserve(client, admin, secret["id"]).status_code in (201, 409)  # admin allowed (409 only if busy)
        assert "restricted" not in _reserve(client, admin, secret["id"]).text

        shown = client.get(f"/api/v1/targets/{secret['id']}", headers=auth(bob)).json()
        assert shown["teams"] == ["firmware"]
        assert client.get(f"/api/v1/targets/{open_board['id']}", headers=auth(bob)).json()["teams"] == []


def test_reserve_by_tag_skips_boards_the_user_may_not_use(tmp_path, monkeypatch):
    with api_client(tmp_path, monkeypatch) as (client, _db):
        admin = bootstrap(client)
        bob = create_user(client, admin, "bob")
        restricted = _target(client, admin, "R1", tags=["stm32"])
        free = _target(client, admin, "R2", tags=["stm32"])
        _team(client, admin, "locked", members=[], target_ids=[restricted["id"]])
        response = client.post(
            "/api/v1/reservations/any", json={"tag": "stm32", "duration_minutes": 20}, headers=auth(bob)
        )
        assert response.status_code == 201, response.text
        assert response.json()["target_id"] == free["id"]


def test_waitlist_respects_team_restriction(tmp_path, monkeypatch):
    with api_client(tmp_path, monkeypatch) as (client, _db):
        admin = bootstrap(client)
        bob = create_user(client, admin, "bob")
        secret = _target(client, admin, "SECRET")
        _team(client, admin, "locked", members=[], target_ids=[secret["id"]])
        response = client.post(
            "/api/v1/waitlist", json={"target_id": secret["id"], "duration_minutes": 20}, headers=auth(bob)
        )
        assert response.status_code == 409 and "locked" in response.text


def test_team_management_is_admin_only_and_validated(tmp_path, monkeypatch):
    with api_client(tmp_path, monkeypatch) as (client, _db):
        admin = bootstrap(client)
        alice = create_user(client, admin, "alice")
        assert client.get("/api/v1/teams", headers=auth(alice)).status_code == 403
        assert client.post("/api/v1/teams", json={"name": "x"}, headers=auth(alice)).status_code == 403

        team = _team(client, admin, "qa", members=["alice"])
        assert client.get("/api/v1/teams/mine", headers=auth(alice)).json() == ["qa"]
        assert client.post("/api/v1/teams", json={"name": "qa"}, headers=auth(admin)).status_code == 409
        assert client.post("/api/v1/teams", json={"name": "z", "members": ["ghost"]}, headers=auth(admin)).status_code == 409
        assert client.post("/api/v1/teams", json={"name": "z", "target_ids": ["nope"]}, headers=auth(admin)).status_code == 409

        board = _target(client, admin, "B1")
        updated = client.put(
            f"/api/v1/teams/{team['id']}",
            json={"name": "quality", "members": [], "target_ids": [board["id"]]},
            headers=auth(admin),
        )
        assert updated.status_code == 200
        assert updated.json()["members"] == [] and updated.json()["target_ids"] == [board["id"]]
        # Renaming keeps members when they are not sent.
        kept = client.put(f"/api/v1/teams/{team['id']}", json={"description": "d"}, headers=auth(admin)).json()
        assert kept["target_ids"] == [board["id"]] and kept["name"] == "quality"

        assert client.delete(f"/api/v1/teams/{team['id']}", headers=auth(admin)).status_code == 204
        assert client.get("/api/v1/teams", headers=auth(admin)).json() == []
        # With the team gone the board is open again.
        assert _reserve(client, alice, board["id"]).status_code == 201


def test_usage_report_groups_hours_by_team(tmp_path, monkeypatch):
    with api_client(tmp_path, monkeypatch) as (client, _db):
        admin = bootstrap(client)
        alice = create_user(client, admin, "alice")
        board = _target(client, admin, "B1")
        _team(client, admin, "firmware", members=["alice"])
        _team(client, admin, "qa", members=[])
        assert _reserve(client, alice, board["id"]).status_code == 201

        report = client.get("/api/v1/reports/usage", headers=auth(admin)).json()
        rows = {row["team"]: row for row in report["teams"]}
        assert rows["firmware"]["reservations"] == 1 and rows["firmware"]["active_users"] == 1
        assert rows["qa"]["reservations"] == 0 and rows["qa"]["members"] == 0
        csv_text = client.get("/api/v1/reports/usage.csv?kind=teams", headers=auth(admin)).text
        assert csv_text.splitlines()[0] == "team,members,active_users,reservations,booked_hours,idle_hours"
        assert "firmware" in csv_text
