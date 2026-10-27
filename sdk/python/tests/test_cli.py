import io
import json

import httpx
import pytest
from targethub_sdk import cli
from targethub_sdk.client import TargetHubClient


def factory(handler):
    return lambda url, token, verify=True: TargetHubClient(
        url, token, verify=verify, transport=httpx.MockTransport(handler)
    )


@pytest.fixture(autouse=True)
def isolated_token(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "TOKEN_FILE", tmp_path / "cfg" / "token")
    monkeypatch.delenv("TARGETHUB_TOKEN", raising=False)


def test_login_stores_a_long_lived_api_token_with_private_permissions(monkeypatch, capsys):
    monkeypatch.setattr("sys.stdin", io.StringIO("s3cret\n"))

    def handler(request):
        if request.url.path.endswith("/auth/token"):
            return httpx.Response(200, json={"access_token": "jwt-1", "refresh_token": "thr_1"})
        assert request.headers["authorization"] == "Bearer jwt-1"
        return httpx.Response(201, json={"id": "k1", "token": "thp_secret", "prefix": "thp_secret"[:12]})

    code = cli.main(["login", "--username", "alice", "--password-stdin"], factory(handler))

    assert code == 0
    assert cli.TOKEN_FILE.read_text() == "thp_secret"
    assert oct(cli.TOKEN_FILE.stat().st_mode & 0o777) == "0o600"
    assert "logged in as alice" in capsys.readouterr().out


def test_targets_prints_json_using_stored_token(capsys):
    cli.save_token("stored")
    seen = {}

    def handler(request):
        seen["auth"] = request.headers.get("authorization")
        return httpx.Response(200, json=[{"id": "t1", "name": "BOARD"}])

    assert cli.main(["targets"], factory(handler)) == 0
    assert seen["auth"] == "Bearer stored"
    assert json.loads(capsys.readouterr().out) == [{"id": "t1", "name": "BOARD"}]


def test_power_rejects_unknown_operation(capsys):
    with pytest.raises(SystemExit) as caught:
        cli.main(["power", "s1", "explode"], factory(lambda request: httpx.Response(200, json={})))
    assert caught.value.code == 2


def test_api_errors_exit_nonzero_with_message(capsys):
    handler = lambda request: httpx.Response(409, json={"detail": "Target already reserved"})  # noqa: E731
    assert cli.main(["power", "s1", "on"], factory(handler)) == 1
    assert "Target already reserved" in capsys.readouterr().err


def test_release_by_target_name_finds_your_reservation(capsys):
    def handler(request):
        if request.url.path == "/api/v1/reservations":
            return httpx.Response(200, json=[{"id": "r7", "target_id": "t1", "user_id": "me"}])
        if request.url.path == "/api/v1/targets":
            return httpx.Response(200, json=[{"id": "t1", "name": "BOARD-1"}])
        assert request.url.path == "/api/v1/reservations/r7/release"
        return httpx.Response(200, json={"id": "r7", "status": "released"})

    assert cli.main(["release", "BOARD-1"], factory(handler)) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "released"


def test_reserve_wait_joins_waitlist_when_busy(capsys, monkeypatch):
    monkeypatch.setattr("time.sleep", lambda _s: None)
    calls = []

    def handler(request):
        calls.append((request.method, request.url.path))
        if request.url.path == "/api/v1/reservations/any":
            return httpx.Response(409, json={"detail": "All targets tagged 'nucleo' are busy for that window"})
        if request.url.path == "/api/v1/waitlist":
            return httpx.Response(201, json={"id": "w1", "status": "waiting", "reservation_id": None})
        if request.url.path == "/api/v1/waitlist/w1":
            return httpx.Response(200, json={"id": "w1", "status": "fulfilled", "reservation_id": "r5"})
        if request.url.path == "/api/v1/reservations":
            return httpx.Response(200, json=[{"id": "r5", "target_id": "t2"}])
        raise AssertionError(request.url.path)

    assert cli.main(["reserve", "--tag", "nucleo", "--minutes", "20", "--wait"], factory(handler)) == 0
    assert json.loads(capsys.readouterr().out)["id"] == "r5"
    assert ("POST", "/api/v1/waitlist") in calls


def test_audit_forwards_filters(capsys):
    seen = {}

    def handler(request):
        seen.update(dict(request.url.params))
        return httpx.Response(200, json=[])

    assert cli.main(["audit", "--action", "session.open", "--limit", "5"], factory(handler)) == 0
    assert seen == {"action": "session.open", "limit": "5"}
