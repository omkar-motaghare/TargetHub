"""Synchronous client for the TargetHub REST API (/api/v1).

Authenticate with a personal API token (``thp_...``, recommended for scripts
and CI) or with :meth:`TargetHubClient.login` for interactive use.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

TERMINAL_OPERATION_STATES = {"completed", "failed", "cancelled", "timed_out"}


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


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat()


class TargetHubClient:
    def __init__(
        self,
        base_url: str,
        token: str | None = None,
        *,
        timeout: float = 60.0,
        verify: bool | str = True,
        transport: httpx.BaseTransport | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.refresh_token: str | None = None
        self._username: str | None = None
        self._http = httpx.Client(
            base_url=f"{self.base_url}/api/v1",
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

    def _request(self, method: str, path: str, *, raw: bool = False, **kwargs: Any) -> Any:
        for attempt in (1, 2):
            headers = {"Authorization": f"Bearer {self.token}"} if self.token else {}
            try:
                response = self._http.request(method, path, headers=headers, **kwargs)
            except httpx.HTTPError as error:
                raise TargetHubError(0, f"cannot reach TargetHub: {error}") from error
            if response.status_code == 401 and attempt == 1 and self.refresh_token and not path.startswith("/auth/"):
                self._refresh()
                continue
            if response.status_code >= 400:
                raise TargetHubError(response.status_code, _detail(response))
            if raw:
                return response.text
            return response.json() if response.content else None
        raise AssertionError("unreachable")  # pragma: no cover

    def _refresh(self) -> None:
        body = self._request("POST", "/auth/refresh", json={"refresh_token": self.refresh_token})
        self.token = body["access_token"]
        self.refresh_token = body.get("refresh_token")

    # ------------------------------------------------------------------ auth

    def login(self, username: str, password: str) -> str:
        body = self._request(
            "POST", "/auth/token", data={"username": username, "password": password, "grant_type": ""}
        )
        self.token = body["access_token"]
        self.refresh_token = body.get("refresh_token")
        self._username = username
        return self.token

    def me(self) -> dict[str, Any]:
        return self._request("GET", "/auth/me")

    def username(self) -> str:
        if self._username is None:
            self._username = self.me()["username"]
        return self._username

    def create_api_token(self, name: str, expires_days: int | None = None) -> dict[str, Any]:
        return self._request("POST", "/auth/api-tokens", json={"name": name, "expires_days": expires_days})

    def list_api_tokens(self) -> list[dict[str, Any]]:
        return self._request("GET", "/auth/api-tokens")

    def revoke_api_token(self, token_id: str) -> None:
        self._request("DELETE", f"/auth/api-tokens/{token_id}")

    # ------------------------------------------------------------------ targets

    def list_targets(self, tag: str | None = None) -> list[dict[str, Any]]:
        return self._request("GET", "/targets", params={"tag": tag} if tag else None)

    def get_target(self, target_id: str) -> dict[str, Any]:
        return self._request("GET", f"/targets/{target_id}")

    def find_target(self, name_or_id: str) -> dict[str, Any]:
        """Look a target up by exact id or (case-insensitive) name."""
        for target in self.list_targets():
            if target["id"] == name_or_id or target["name"].lower() == name_or_id.lower():
                return target
        raise TargetHubError(404, f"Target '{name_or_id}' not found")

    def policy(self) -> dict[str, Any]:
        return self._request("GET", "/settings/policy")

    # ------------------------------------------------------------------ reservations

    def list_reservations(self, target_id: str | None = None, status: str | None = None) -> list[dict[str, Any]]:
        params = {key: value for key, value in {"target_id": target_id, "status": status}.items() if value}
        return self._request("GET", "/reservations", params=params or None)

    def calendar(self, start: datetime | None = None, end: datetime | None = None) -> list[dict[str, Any]]:
        params = {}
        if start:
            params["from"] = _iso(start)
        if end:
            params["to"] = _iso(end)
        return self._request("GET", "/reservations/calendar", params=params or None)

    def create_reservation(
        self, target_id: str, starts_at: str, ends_at: str, note: str | None = None
    ) -> dict[str, Any]:
        body: dict[str, Any] = {"target_id": target_id, "starts_at": starts_at, "ends_at": ends_at}
        if note:
            body["note"] = note
        return self._request("POST", "/reservations", json=body)

    def reserve(self, target: str, minutes: int = 60, note: str | None = None) -> dict[str, Any]:
        """Reserve a target (name or id) starting now."""
        now = datetime.now(UTC)
        return self.create_reservation(
            self.find_target(target)["id"], _iso(now), _iso(now + timedelta(minutes=minutes)), note
        )

    def reserve_any(self, tag: str, minutes: int = 60, note: str | None = None) -> dict[str, Any]:
        return self._request(
            "POST", "/reservations/any", json={"tag": tag, "duration_minutes": minutes, "note": note}
        )

    def extend_reservation(self, reservation_id: str, minutes: int) -> dict[str, Any]:
        return self._request("POST", f"/reservations/{reservation_id}/extend", json={"extend_minutes": minutes})

    def release_reservation(self, reservation_id: str) -> dict[str, Any]:
        return self._request("POST", f"/reservations/{reservation_id}/release")

    # ------------------------------------------------------------------ waitlist

    def join_waitlist(
        self, *, target_id: str | None = None, tag: str | None = None, minutes: int = 60, note: str | None = None
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            "/waitlist",
            json={"target_id": target_id, "tag": tag, "duration_minutes": minutes, "note": note},
        )

    def list_waitlist(self) -> list[dict[str, Any]]:
        return self._request("GET", "/waitlist")

    def get_waitlist_entry(self, entry_id: str) -> dict[str, Any]:
        return self._request("GET", f"/waitlist/{entry_id}")

    def leave_waitlist(self, entry_id: str) -> dict[str, Any]:
        return self._request("DELETE", f"/waitlist/{entry_id}")

    def wait_for_reservation(
        self,
        *,
        target_id: str | None = None,
        tag: str | None = None,
        minutes: int = 60,
        timeout: float = 3600,
        poll: float = 5,
        note: str | None = None,
    ) -> dict[str, Any]:
        """Join the waitlist and block until a reservation is granted (or raise on timeout).

        Handy in CI: ``wait_for_reservation(tag="stm32-nucleo", minutes=30)``.
        """
        entry = self.join_waitlist(target_id=target_id, tag=tag, minutes=minutes, note=note)
        deadline = time.monotonic() + timeout
        try:
            while True:
                if entry.get("reservation_id"):
                    reservation_id = entry["reservation_id"]
                    return next(
                        item for item in self.list_reservations(status="active") if item["id"] == reservation_id
                    )
                if entry["status"] not in {"waiting", "processing"}:
                    raise TargetHubError(409, f"Waitlist entry {entry['status']}")
                if time.monotonic() >= deadline:
                    raise TargetHubError(408, "Timed out waiting for a target")
                time.sleep(poll)
                entry = self.get_waitlist_entry(entry["id"])
        except BaseException:
            if entry.get("status") == "waiting":
                try:
                    self.leave_waitlist(entry["id"])
                except TargetHubError:
                    pass
            raise

    # ------------------------------------------------------------------ sessions

    def list_sessions(self) -> list[dict[str, Any]]:
        return self._request("GET", "/sessions")

    def open_session(
        self, reservation_id: str, capability_type: str, capability_id: str | None = None
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            "/sessions",
            json={"reservation_id": reservation_id, "capability_type": capability_type, "capability_id": capability_id},
        )

    def close_session(self, session_id: str) -> dict[str, Any]:
        return self._request("POST", f"/sessions/{session_id}/close")

    def operations(self, session_id: str) -> list[str]:
        return self._request("GET", f"/sessions/{session_id}/operations")["operations"]

    def execute(self, session_id: str, operation: str, **params: Any) -> dict[str, Any]:
        return self._request(
            "POST", f"/sessions/{session_id}/execute", json={"operation": operation, "params": params}
        )

    def submit(self, session_id: str, operation: str, **params: Any) -> dict[str, Any]:
        """Queue an Agent operation without waiting (returns ``operation_id``)."""
        return self._request(
            "POST",
            f"/sessions/{session_id}/execute",
            params={"wait": "false"},
            json={"operation": operation, "params": params},
        )

    def operation_status(self, session_id: str, operation_id: str) -> dict[str, Any]:
        return self._request("GET", f"/sessions/{session_id}/operations/{operation_id}")

    def wait_operation(
        self, session_id: str, operation_id: str, timeout: float = 900, poll: float = 1.5
    ) -> dict[str, Any]:
        deadline = time.monotonic() + timeout
        while True:
            status = self.operation_status(session_id, operation_id)
            if status["status"] in TERMINAL_OPERATION_STATES:
                if status["status"] != "completed":
                    raise TargetHubError(409, status.get("message") or f"operation {status['status']}")
                return status
            if time.monotonic() >= deadline:
                raise TargetHubError(408, "Timed out waiting for the operation")
            time.sleep(poll)

    # ------------------------------------------------------------------ capability helpers

    def serial_open(self, session_id: str) -> dict[str, Any]:
        return self.execute(session_id, "open")

    def serial_write(self, session_id: str, text: str) -> dict[str, Any]:
        return self._request("POST", f"/sessions/{session_id}/serial/write", json={"text": text})

    def serial_read(self, session_id: str, size: int = 4096, wait_ms: int = 0) -> str:
        params: dict[str, Any] = {"size": size}
        if wait_ms:
            params["wait_ms"] = wait_ms
        body = self._request("GET", f"/sessions/{session_id}/serial/read", params=params)
        return (body.get("data") or {}).get("data_text", "")

    def serial_expect(self, session_id: str, pattern: str, timeout: float = 30) -> str:
        """Read until ``pattern`` appears (plain substring); returns everything read."""
        deadline = time.monotonic() + timeout
        received = ""
        while pattern not in received:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TargetHubError(408, f"'{pattern}' not seen within {timeout}s")
            received += self.serial_read(session_id, size=65536, wait_ms=int(min(remaining, 2) * 1000))
        return received

    def serial_log(self, session_id: str, include_input: bool = False) -> str:
        params = {"include_input": "true"} if include_input else None
        return self._request("GET", f"/sessions/{session_id}/serial/log", params=params, raw=True)

    def serial_ws_url(self, session_id: str) -> str:
        return self.base_url.replace("http", "ws", 1) + f"/api/v1/sessions/{session_id}/serial/ws"

    def power(self, session_id: str, operation: str) -> dict[str, Any]:
        return self.execute(session_id, operation)

    def deploy(self, session_id: str, url: str, sha256: str, wait: bool = True, timeout: float = 900) -> dict[str, Any]:
        queued = self.submit(session_id, "deploy", url=url, sha256=sha256)
        if not wait or not queued.get("operation_id"):
            return queued
        return self.wait_operation(session_id, queued["operation_id"], timeout=timeout)

    # ------------------------------------------------------------------ notifications

    def notifications(self, unread: bool = False) -> list[dict[str, Any]]:
        return self._request("GET", "/notifications", params={"unread": "true"} if unread else None)

    # ------------------------------------------------------------------ admin

    def list_agents(self) -> list[dict[str, Any]]:
        return self._request("GET", "/agents")

    def create_enrollment(self, agent_name: str) -> dict[str, Any]:
        return self._request("POST", "/agents/enrollments", json={"agent_name": agent_name})

    def audit(self, **filters: str | int) -> list[dict[str, Any]]:
        return self._request("GET", "/audit", params=filters)
