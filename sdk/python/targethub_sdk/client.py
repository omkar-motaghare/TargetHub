"""Thin synchronous client for the TargetHub REST API (/api/v1)."""

from __future__ import annotations

from typing import Any

import httpx


class TargetHubError(Exception):
    def __init__(self, status_code: int, detail: str):
        super().__init__(f"{status_code}: {detail}")
        self.status_code = status_code
        self.detail = detail


def _detail(response: httpx.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        return response.text or response.reason_phrase
    detail = body.get("detail") if isinstance(body, dict) else None
    if isinstance(detail, list):
        return "; ".join(str(item.get("msg", item)) if isinstance(item, dict) else str(item) for item in detail)
    return str(detail if detail is not None else body)


class TargetHubClient:
    def __init__(
        self,
        base_url: str,
        token: str | None = None,
        *,
        timeout: float = 30.0,
        verify: bool | str = True,
        transport: httpx.BaseTransport | None = None,
    ):
        self.token = token
        self._http = httpx.Client(
            base_url=f"{base_url.rstrip('/')}/api/v1",
            timeout=timeout,
            verify=verify,
            transport=transport,
        )

    def __enter__(self) -> TargetHubClient:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def close(self) -> None:
        self._http.close()

    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        headers = {"Authorization": f"Bearer {self.token}"} if self.token else {}
        try:
            response = self._http.request(method, path, headers=headers, **kwargs)
        except httpx.HTTPError as error:
            raise TargetHubError(0, f"cannot reach TargetHub: {error}") from error
        if response.status_code >= 400:
            raise TargetHubError(response.status_code, _detail(response))
        return response.json() if response.content else None

    # --- auth
    def login(self, username: str, password: str) -> str:
        body = self._request(
            "POST", "/auth/token", data={"username": username, "password": password, "grant_type": ""}
        )
        self.token = body["access_token"]
        return self.token

    def me(self) -> dict[str, Any]:
        return self._request("GET", "/auth/me")

    # --- targets and reservations
    def list_targets(self) -> list[dict[str, Any]]:
        return self._request("GET", "/targets")

    def get_target(self, target_id: str) -> dict[str, Any]:
        return self._request("GET", f"/targets/{target_id}")

    def list_reservations(self, target_id: str | None = None) -> list[dict[str, Any]]:
        params = {"target_id": target_id} if target_id else None
        return self._request("GET", "/reservations", params=params)

    def create_reservation(self, target_id: str, starts_at: str, ends_at: str) -> dict[str, Any]:
        return self._request(
            "POST",
            "/reservations",
            json={
                "target_id": target_id,
                "user_id": self.me()["username"],
                "starts_at": starts_at,
                "ends_at": ends_at,
            },
        )

    def release_reservation(self, reservation_id: str) -> dict[str, Any]:
        return self._request(
            "POST", f"/reservations/{reservation_id}/release", params={"user_id": self.me()["username"]}
        )

    # --- sessions
    def list_sessions(self) -> list[dict[str, Any]]:
        return self._request("GET", "/sessions")

    def open_session(
        self, reservation_id: str, capability_type: str, capability_id: str | None = None
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            "/sessions",
            json={
                "reservation_id": reservation_id,
                "user_id": self.me()["username"],
                "capability_type": capability_type,
                "capability_id": capability_id,
            },
        )

    def close_session(self, session_id: str) -> dict[str, Any]:
        return self._request(
            "POST", f"/sessions/{session_id}/close", params={"user_id": self.me()["username"]}
        )

    def operations(self, session_id: str) -> list[str]:
        return self._request("GET", f"/sessions/{session_id}/operations")["operations"]

    def execute(self, session_id: str, operation: str, **params: Any) -> dict[str, Any]:
        return self._request(
            "POST", f"/sessions/{session_id}/execute", json={"operation": operation, "params": params}
        )

    # --- capability helpers
    def serial_open(self, session_id: str) -> dict[str, Any]:
        return self.execute(session_id, "open")

    def serial_write(self, session_id: str, text: str) -> dict[str, Any]:
        return self._request("POST", f"/sessions/{session_id}/serial/write", json={"text": text})

    def serial_read(self, session_id: str, size: int = 4096) -> str:
        body = self._request("GET", f"/sessions/{session_id}/serial/read", params={"size": size})
        return body["data"].get("data_text", "")

    def power(self, session_id: str, operation: str) -> dict[str, Any]:
        return self.execute(session_id, operation)

    def deploy(self, session_id: str, url: str, sha256: str) -> dict[str, Any]:
        return self.execute(session_id, "deploy", url=url, sha256=sha256)

    # --- admin
    def list_agents(self) -> list[dict[str, Any]]:
        return self._request("GET", "/agents")

    def create_enrollment(self, agent_name: str) -> dict[str, Any]:
        return self._request("POST", "/agents/enrollments", json={"agent_name": agent_name})

    def audit(self, **filters: str | int) -> list[dict[str, Any]]:
        return self._request("GET", "/audit", params=filters)
