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


def test_login_stores_token_with_private_permissions(monkeypatch, capsys):
    monkeypatch.setattr("sys.stdin", io.StringIO("s3cret\n"))
    handler = lambda request: httpx.Response(200, json={"access_token": "jwt-1"})  # noqa: E731

    code = cli.main(["login", "--username", "alice", "--password-stdin"], factory(handler))

    assert code == 0
    assert cli.TOKEN_FILE.read_text() == "jwt-1"
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
    assert cli.main(["release", "r1"], factory(handler)) == 1
    assert "Target already reserved" in capsys.readouterr().err


def test_audit_forwards_filters(capsys):
    seen = {}

    def handler(request):
        seen.update(dict(request.url.params))
        return httpx.Response(200, json=[])

    assert cli.main(["audit", "--action", "session.open", "--limit", "5"], factory(handler)) == 0
    assert seen == {"action": "session.open", "limit": "5"}
