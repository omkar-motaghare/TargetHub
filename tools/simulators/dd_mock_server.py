#!/usr/bin/env python3
"""Mock of the DD Endpoint Control REST API, for testing TargetHub without hardware.

Implements the documented contract:
  GET|POST /api/endpoints/control                       (query or JSON body)
  GET|POST /api/hubs/<mac>/nodes/<id>/endpoints/<n>/<state>
  GET      /api/hubs/<mac>/nodes/<id>/endpoints/<n>     (last known state)
  202 on accepted commands; the stored state changes after --confirm-delay
  seconds (asynchronous device confirmation); 400/401/404/423/500 errors;
  API key via X-API-Key, Authorization: Bearer or ?api_key=.

Extra test controls (not part of the real API):
  POST /_mock/emergency?active=1|0      toggle the emergency lock (423)
  POST /_mock/fail-next?status=500      make the next control request fail
  GET  /_mock/state                     dump every endpoint
  POST /_mock/disconnect?node_id=1      device stops confirming commands

Runs on Windows, Linux and macOS with only the Python standard library:
  python dd_mock_server.py --port 5003 --hub-mac AA:BB:CC:DD:EE:FF --nodes 2 --endpoints 10
"""

from __future__ import annotations

import argparse
import json
import threading
import time
import urllib.parse
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

TRUE_VALUES = {"on", "1", "true", "high"}


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


class DDState:
    def __init__(self, hub_mac: str, nodes: int, endpoints: int, confirm_delay: float, api_key: str | None):
        self.lock = threading.Lock()
        self.hub_mac = hub_mac.upper()
        self.confirm_delay = confirm_delay
        self.api_key = api_key
        self.emergency = False
        self.fail_next: int | None = None
        self.disconnected: set[int] = set()
        self.commands: list[dict] = []
        self.nodes = {
            node_id: {
                "node_pk": node_id + 3,
                "hub_mac": self.hub_mac,
                "node_id": node_id,
                "display_name": f"Node {node_id}",
                "location": "Unassigned",
                "board_type": "relay",
                "relay_board_count": 2,
                "endpoint_capacity": endpoints,
                "is_connected": True,
                "last_seen": _now(),
            }
            for node_id in range(1, nodes + 1)
        }
        self.endpoints = {
            (node_id, number): {
                "endpoint_number": number,
                "endpoint_name": f"Relay {number}",
                "current_state": "OFF",
                "updated_at": _now(),
            }
            for node_id in self.nodes
            for number in range(1, endpoints + 1)
        }

    def control(self, hub_mac: str, node_id: int, endpoint: int, state: str) -> tuple[int, dict]:
        with self.lock:
            if self.fail_next is not None:
                status, self.fail_next = self.fail_next, None
                return status, {"status": "error", "message": "Injected failure"}
            if hub_mac.upper() != self.hub_mac or node_id not in self.nodes:
                return 404, {"status": "error", "message": "Node not found"}
            if (node_id, endpoint) not in self.endpoints:
                return 404, {"status": "error", "message": "Endpoint not found"}
            if self.emergency:
                return 423, {"status": "error", "message": "Hub is under emergency lock", "emergency_active": True}
            normalized = "ON" if str(state).strip().lower() in TRUE_VALUES else "OFF"
            self.commands.append({"node_id": node_id, "endpoint": endpoint, "state": normalized, "at": time.time()})
            previous = dict(self.endpoints[(node_id, endpoint)])
            node = dict(self.nodes[node_id])
        if node_id not in self.disconnected:
            timer = threading.Timer(self.confirm_delay, self._apply, args=(node_id, endpoint, normalized))
            timer.daemon = True
            timer.start()
        return 202, {
            "status": "accepted",
            "message": "Command published. Waiting for device confirmation. Retries are capped at 6 total sends.",
            "request": {"hub_mac": hub_mac.upper(), "node_id": node_id, "endpoint": endpoint, "state": normalized},
            "node": node,
            "emergency_active": False,
            "last_known_endpoint_state": previous,
        }

    def _apply(self, node_id: int, endpoint: int, state: str) -> None:
        with self.lock:
            self.endpoints[(node_id, endpoint)].update(current_state=state, updated_at=_now())
            self.nodes[node_id]["last_seen"] = _now()

    def status(self, hub_mac: str, node_id: int, endpoint: int) -> tuple[int, dict]:
        with self.lock:
            if hub_mac.upper() != self.hub_mac or node_id not in self.nodes:
                return 404, {"status": "error", "message": "Node not found"}
            if (node_id, endpoint) not in self.endpoints:
                return 404, {"status": "error", "message": "Endpoint not found"}
            return 200, {
                "status": "success",
                "node": dict(self.nodes[node_id]),
                "endpoint": dict(self.endpoints[(node_id, endpoint)]),
                "emergency_active": self.emergency,
            }


def make_handler(state: DDState):
    class Handler(BaseHTTPRequestHandler):
        server_version = "DDMock/1.0"

        def _send(self, status: int, payload: dict) -> None:
            body = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _authorized(self, query: dict) -> bool:
            if not state.api_key:
                return True
            presented = (
                self.headers.get("X-API-Key")
                or (self.headers.get("Authorization", "").removeprefix("Bearer ").strip() or None)
                or (query.get("api_key") or [None])[0]
            )
            return presented == state.api_key

        def _body(self) -> dict:
            length = int(self.headers.get("Content-Length") or 0)
            if not length:
                return {}
            try:
                payload = json.loads(self.rfile.read(length).decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                return {}
            return payload if isinstance(payload, dict) else {}

        def _handle(self) -> None:
            parsed = urllib.parse.urlparse(self.path)
            query = urllib.parse.parse_qs(parsed.query)
            parts = [urllib.parse.unquote(part) for part in parsed.path.strip("/").split("/")]

            if parts[:1] == ["_mock"]:
                return self._mock(parts[1:] if len(parts) > 1 else [""], query)
            if not self._authorized(query):
                return self._send(401, {"status": "error", "message": "API key is required"})

            try:
                if parts == ["api", "endpoints", "control"]:
                    fields = {key: values[0] for key, values in query.items()}
                    fields.update(self._body())
                    missing = [name for name in ("hub_mac", "node_id", "endpoint", "state") if fields.get(name) in (None, "")]
                    if missing:
                        return self._send(400, {"status": "error", "message": f"Missing fields: {', '.join(missing)}"})
                    status, payload = state.control(
                        str(fields["hub_mac"]), int(fields["node_id"]), int(fields["endpoint"]), str(fields["state"])
                    )
                    return self._send(status, payload)
                if len(parts) == 8 and parts[:2] == ["api", "hubs"] and parts[3] == "nodes" and parts[5] == "endpoints":
                    status, payload = state.control(parts[2], int(parts[4]), int(parts[6]), parts[7])
                    return self._send(status, payload)
                if len(parts) == 7 and parts[:2] == ["api", "hubs"] and parts[3] == "nodes" and parts[5] == "endpoints":
                    if self.command != "GET":
                        return self._send(405, {"status": "error", "message": "Use GET"})
                    status, payload = state.status(parts[2], int(parts[4]), int(parts[6]))
                    return self._send(status, payload)
            except ValueError:
                return self._send(400, {"status": "error", "message": "node_id and endpoint must be integers"})
            return self._send(404, {"status": "error", "message": "Not found"})

        def _mock(self, parts: list[str], query: dict) -> None:
            action = parts[0]
            if action == "emergency":
                state.emergency = (query.get("active") or ["1"])[0] in {"1", "true", "on"}
                return self._send(200, {"emergency_active": state.emergency})
            if action == "fail-next":
                state.fail_next = int((query.get("status") or ["500"])[0])
                return self._send(200, {"fail_next": state.fail_next})
            if action == "disconnect":
                node_id = int((query.get("node_id") or ["1"])[0])
                connected = (query.get("connected") or ["0"])[0] in {"1", "true"}
                (state.disconnected.discard if connected else state.disconnected.add)(node_id)
                state.nodes[node_id]["is_connected"] = connected
                return self._send(200, {"node_id": node_id, "connected": connected})
            if action == "state":
                with state.lock:
                    endpoints = {f"{node}/{number}": value["current_state"] for (node, number), value in state.endpoints.items()}
                    return self._send(200, {"emergency_active": state.emergency, "endpoints": endpoints, "commands": state.commands[-50:]})
            return self._send(404, {"status": "error", "message": "Unknown mock control"})

        def do_GET(self):  # noqa: N802
            self._handle()

        def do_POST(self):  # noqa: N802
            self._handle()

        def log_message(self, fmt, *args):  # quieter default logging
            if not getattr(self.server, "quiet", False):
                super().log_message(fmt, *args)

    return Handler


def serve(host: str, port: int, state: DDState, quiet: bool = False) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer((host, port), make_handler(state))
    server.quiet = quiet  # type: ignore[attr-defined]
    server.daemon_threads = True
    return server


def main() -> int:
    parser = argparse.ArgumentParser(description="Mock DD Endpoint Control API")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=5003)
    parser.add_argument("--hub-mac", default="AA:BB:CC:DD:EE:FF")
    parser.add_argument("--nodes", type=int, default=2)
    parser.add_argument("--endpoints", type=int, default=10)
    parser.add_argument("--confirm-delay", type=float, default=0.5, help="seconds until the device 'confirms'")
    parser.add_argument("--api-key", default=None, help="require this API key")
    args = parser.parse_args()
    state = DDState(args.hub_mac, args.nodes, args.endpoints, args.confirm_delay, args.api_key)
    server = serve(args.host, args.port, state)
    print(f"DD mock listening on http://{args.host}:{args.port} hub_mac={state.hub_mac} "
          f"nodes=1..{args.nodes} endpoints=1..{args.endpoints}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
