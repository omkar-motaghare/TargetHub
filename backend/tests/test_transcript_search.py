"""Transcript search across sessions."""

from __future__ import annotations

from app.repositories.serial_log_repository import SerialLogRepository
from tests.helpers import api_client, auth, bootstrap, create_user, open_session, reserve


def _serial_session(client, admin, token, name):
    target = client.post(
        "/api/v1/targets",
        json={"name": name, "capabilities": [{"name": "Console", "capability_type": "serial", "provider_config": {"mode": "simulated"}}]},
        headers=auth(admin),
    ).json()
    reservation = reserve(client, token, target["id"])
    return target, open_session(client, token, reservation["id"], "serial")


def test_search_finds_text_split_across_chunks_and_scopes_to_the_owner(tmp_path, monkeypatch):
    with api_client(tmp_path, monkeypatch) as (client, session_local):
        admin = bootstrap(client)
        alice = create_user(client, admin, "alice")
        bob = create_user(client, admin, "bob")
        _t1, s1 = _serial_session(client, admin, alice, "BOARD-A")
        _t2, s2 = _serial_session(client, admin, bob, "BOARD-B")
        with session_local() as db:
            logs = SerialLogRepository(db)
            logs.append(s1["id"], "out", "boot ok\r\nKernel pan")
            logs.append(s1["id"], "out", "ic - not syncing: VFS\r\nrebooting\r\n")
            logs.append(s1["id"], "in", "secret-command\r")
            logs.append(s2["id"], "out", "\x1b[31mkernel panic\x1b[0m on bob's board\r\n")

        hits = client.get("/api/v1/transcripts/search", params={"q": "KERNEL PANIC"}, headers=auth(alice)).json()
        assert [h["session_id"] for h in hits["hits"]] == [s1["id"]]
        hit = hits["hits"][0]
        assert hit["target"] == "BOARD-A" and "not syncing" in hit["text"] and hit["before"] == "boot ok"
        assert hit["after"] == "rebooting"

        # Typed input is only searched on request.
        assert client.get("/api/v1/transcripts/search", params={"q": "secret-command"}, headers=auth(alice)).json()["hits"] == []
        typed = client.get(
            "/api/v1/transcripts/search", params={"q": "secret-command", "include_input": "true"}, headers=auth(alice)
        ).json()
        assert len(typed["hits"]) == 1

        # Non-admins never see other users' sessions, even when asking for all.
        mine = client.get("/api/v1/transcripts/search", params={"q": "panic", "all_users": "true"}, headers=auth(bob)).json()
        assert {h["user_id"] for h in mine["hits"]} == {"bob"}
        assert "\x1b" not in mine["hits"][0]["text"]
        everyone = client.get("/api/v1/transcripts/search", params={"q": "panic", "all_users": "true"}, headers=auth(admin)).json()
        assert {h["user_id"] for h in everyone["hits"]} == {"alice", "bob"}


def test_search_rejects_tiny_queries_and_requires_login(tmp_path, monkeypatch):
    with api_client(tmp_path, monkeypatch) as (client, _db):
        admin = bootstrap(client)
        assert client.get("/api/v1/transcripts/search", params={"q": "a"}, headers=auth(admin)).status_code == 422
        assert client.get("/api/v1/transcripts/search", params={"q": "panic"}).status_code == 401
