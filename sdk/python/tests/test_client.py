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


def test_reservation_uses_authenticated_username():
    client, recorder = make_client(
        {
            ("GET", "/api/v1/auth/me"): {"username": "alice"},
            ("POST", "/api/v1/reservations"): {"id": "r1"},
        }
    )
    assert client.create_reservation("t1", "2030-01-01T00:00:00Z", "2030-01-01T01:00:00Z") == {"id": "r1"}
    body = httpx.Response(200, content=recorder.requests[-1].content).json()
    assert body == {
        "target_id": "t1",
        "user_id": "alice",
        "starts_at": "2030-01-01T00:00:00Z",
        "ends_at": "2030-01-01T01:00:00Z",
    }


def test_execute_and_helpers_send_expected_payloads():
    client, recorder = make_client(
        {
            ("POST", "/api/v1/sessions/s1/execute"): {"message": "ok", "data": {}},
            ("GET", "/api/v1/sessions/s1/serial/read"): {"data": {"data_text": "hi"}},
            ("POST", "/api/v1/sessions/s1/serial/write"): {"message": "ok"},
        }
    )
    client.power("s1", "cycle")
    client.deploy("s1", "https://x/fw.bin", "a" * 64)
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
