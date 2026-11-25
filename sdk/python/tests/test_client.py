import httpx
import pytest

from targethub_sdk import TargetHubClient, TargetHubError


class Recorder:
    def __init__(self, routes):
        self.routes = routes
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        handler = self.routes[(request.method, request.url.path)]
        return handler(request) if callable(handler) else httpx.Response(200, json=handler)


def make_client(routes, token="tok") -> tuple[TargetHubClient, Recorder]:
    recorder = Recorder(routes)
    return TargetHubClient("http://hub.test/", token, transport=httpx.MockTransport(recorder)), recorder


def test_login_posts_form_and_keeps_token():
    client, recorder = make_client({("POST", "/api/v1/auth/token"): {"access_token": "abc"}}, token=None)
    assert client.login("alice", "pw") == "abc"
    assert client.token == "abc"
    assert recorder.requests[0].content == b"username=alice&password=pw&grant_type="


def test_requests_carry_bearer_token():
    client, recorder = make_client({("GET", "/api/v1/targets"): [{"id": "t1"}]})
    assert client.list_targets() == [{"id": "t1"}]
    assert recorder.requests[0].headers["authorization"] == "Bearer tok"


def test_reservation_is_made_as_the_authenticated_user():
    client, recorder = make_client({("POST", "/api/v1/reservations"): {"id": "r1"}})
    assert client.create_reservation("t1", "2030-01-01T00:00:00Z", "2030-01-01T01:00:00Z") == {"id": "r1"}
    body = httpx.Response(200, content=recorder.requests[-1].content).json()
    assert body == {"target_id": "t1", "starts_at": "2030-01-01T00:00:00Z", "ends_at": "2030-01-01T01:00:00Z"}


def test_reserve_by_name_resolves_the_target():
    client, recorder = make_client(
        {
            ("GET", "/api/v1/targets"): [{"id": "t9", "name": "BOARD-9"}],
            ("POST", "/api/v1/reservations"): {"id": "r1"},
        }
    )
    client.reserve("board-9", minutes=15, note="smoke")
    body = httpx.Response(200, content=recorder.requests[-1].content).json()
    assert body["target_id"] == "t9" and body["note"] == "smoke"


def test_expired_access_token_is_refreshed_once():
    state = {"calls": 0}

    def targets(request):
        state["calls"] += 1
        if request.headers["authorization"] == "Bearer old":
            return httpx.Response(401, json={"detail": "Invalid or expired token"})
        return httpx.Response(200, json=[])

    client, recorder = make_client(
        {
            ("GET", "/api/v1/targets"): targets,
            ("POST", "/api/v1/auth/refresh"): {"access_token": "new", "refresh_token": "thr_2"},
        },
        token="old",
    )
    client.refresh_token = "thr_1"
    assert client.list_targets() == []
    assert client.token == "new" and client.refresh_token == "thr_2" and state["calls"] == 2


def test_deploy_submits_async_and_waits_for_completion():
    statuses = iter(["in_progress", "completed"])
    client, recorder = make_client(
        {
            ("POST", "/api/v1/sessions/s1/execute"): {"operation_id": "op1", "status": "pending"},
            ("GET", "/api/v1/sessions/s1/operations/op1"): lambda _r: httpx.Response(
                200, json={"status": next(statuses), "message": "Deployment complete"}
            ),
        }
    )
    result = client.deploy("s1", "https://x/fw.bin", "a" * 64)
    assert result["status"] == "completed"
    assert recorder.requests[0].url.params["wait"] == "false"


def test_serial_expect_reads_until_pattern():
    chunks = iter(["boot", "ing...\nboard> "])
    client, recorder = make_client(
        {("GET", "/api/v1/sessions/s1/serial/read"): lambda _r: httpx.Response(200, json={"data": {"data_text": next(chunks)}})}
    )
    assert client.serial_expect("s1", "board>", timeout=5).endswith("board> ")
    assert recorder.requests[0].url.params["wait_ms"]


def test_execute_and_helpers_send_expected_payloads():
    client, recorder = make_client(
        {
            ("POST", "/api/v1/sessions/s1/execute"): {"message": "ok", "data": {}},
            ("GET", "/api/v1/sessions/s1/operations/op"): {"status": "completed"},
            ("GET", "/api/v1/sessions/s1/serial/read"): {"data": {"data_text": "hi"}},
            ("POST", "/api/v1/sessions/s1/serial/write"): {"message": "ok"},
        }
    )
    client.power("s1", "cycle")
    client.deploy("s1", "https://x/fw.bin", "a" * 64, wait=False)
    client.serial_write("s1", "ls\n")
    assert client.serial_read("s1", size=10) == "hi"

    import json

    assert json.loads(recorder.requests[0].content) == {"operation": "cycle", "params": {}}
    assert json.loads(recorder.requests[1].content) == {
        "operation": "deploy",
        "params": {"url": "https://x/fw.bin", "sha256": "a" * 64},
    }
    assert recorder.requests[3].url.params["size"] == "10"


@pytest.mark.parametrize(
    ("status", "body", "expected"),
    [
        (409, {"detail": "Target already reserved"}, "Target already reserved"),
        (422, {"detail": [{"msg": "Field required"}]}, "Field required"),
        (500, None, "Internal Server Error"),
    ],
)
def test_http_errors_become_targethub_errors(status, body, expected):
    def respond(_request):
        return httpx.Response(status, json=body) if body else httpx.Response(status)

    client, _ = make_client({("GET", "/api/v1/targets"): respond})
    with pytest.raises(TargetHubError) as caught:
        client.list_targets()
    assert caught.value.status_code == status
    assert caught.value.detail == expected


def test_network_failure_is_reported_with_status_zero():
    def boom(request):
        raise httpx.ConnectError("refused", request=request)

    client, _ = make_client({("GET", "/api/v1/targets"): boom})
    with pytest.raises(TargetHubError) as caught:
        client.list_targets()
    assert caught.value.status_code == 0


def test_upload_artifact_sends_multipart_and_deploy_by_artifact_id(tmp_path):
    import json

    firmware = tmp_path / "fw.bin"
    firmware.write_bytes(b"image")
    client, recorder = make_client(
        {
            ("POST", "/api/v1/artifacts"): {"id": "a1", "sha256": "b" * 64},
            ("GET", "/api/v1/artifacts"): [{"id": "a1"}],
            ("DELETE", "/api/v1/artifacts/a1"): lambda _r: httpx.Response(204),
            ("POST", "/api/v1/sessions/s1/execute"): {"message": "ok", "data": {}},
        }
    )
    assert client.upload_artifact(str(firmware), "rc1")["id"] == "a1"
    upload = recorder.requests[0]
    assert upload.headers["content-type"].startswith("multipart/form-data")
    assert b'filename="fw.bin"' in upload.content and b"image" in upload.content and b"rc1" in upload.content

    assert client.list_artifacts(mine=True) == [{"id": "a1"}]
    assert recorder.requests[1].url.params["mine"] == "true"
    client.delete_artifact("a1")

    client.deploy("s1", artifact_id="a1", wait=False)
    assert json.loads(recorder.requests[3].content)["params"] == {"artifact_id": "a1"}

    import pytest as _pytest

    with _pytest.raises(ValueError):
        client.deploy("s1")


def test_usage_report_requests_the_period_ending_now():
    client, recorder = make_client(
        {
            ("GET", "/api/v1/reports/usage"): {"totals": {}},
            ("GET", "/api/v1/reports/usage.csv"): lambda _r: httpx.Response(200, text="name\nB1\n"),
        }
    )
    assert client.usage_report(days=7) == {"totals": {}}
    params = recorder.requests[0].url.params
    assert "from" in params and "to" in params
    assert client.usage_report_csv("idle", days=7) == "name\nB1\n"
    assert recorder.requests[1].url.params["kind"] == "idle"


def test_team_helpers_call_the_team_endpoints():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.path)
        return httpx.Response(200, json=["firmware"] if request.url.path.endswith("/mine") else [])

    client = TargetHubClient("http://hub", token="t", transport=httpx.MockTransport(handler))
    assert client.my_teams() == ["firmware"]
    assert client.list_teams() == []
    assert seen == ["/api/v1/teams/mine", "/api/v1/teams"]
