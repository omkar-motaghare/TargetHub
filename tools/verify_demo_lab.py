#!/usr/bin/env python3
"""Smoke-check a running demo lab (tools/demo_lab.py) end to end.

Reserves DEMO-BOARD-01, powers it on through DD, watches the virtual board boot
on the WebSocket console, runs a command, power-resets it and checks the reboot
and the stored transcript. Exit code 0 means every step passed.

  pip install httpx websockets      # or run with the backend virtualenv
  python tools/verify_demo_lab.py --hub http://localhost:8000 --admin admin --password '...'
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import UTC, datetime, timedelta

import httpx
from websockets.sync.client import connect


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--hub", default="http://localhost:8000")
    parser.add_argument("--admin", default="admin")
    parser.add_argument("--password", required=True)
    args = parser.parse_args()
    api = args.hub.rstrip("/") + "/api/v1"
    http = httpx.Client(timeout=60)
    failures: list[str] = []

    def check(label: str, ok: bool, detail: str = "") -> None:
        print(f"[{'PASS' if ok else 'FAIL'}] {label}{(' - ' + detail) if detail else ''}")
        if not ok:
            failures.append(label)

    token = http.post(f"{api}/auth/token", data={"username": args.admin, "password": args.password}).json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    target = next(t for t in http.get(f"{api}/targets", headers=headers).json() if t["name"] == "DEMO-BOARD-01")
    for previous in http.get(f"{api}/reservations", params={"target_id": target["id"], "status": "active"}, headers=headers).json():
        if previous["user_id"] == args.admin:  # leftovers from an earlier run
            http.post(f"{api}/reservations/{previous['id']}/release", headers=headers)
    now = datetime.now(UTC)
    reservation = http.post(
        f"{api}/reservations",
        json={"target_id": target["id"], "starts_at": now.isoformat(), "ends_at": (now + timedelta(minutes=20)).isoformat()},
        headers=headers,
    )
    check("reserve DEMO-BOARD-01", reservation.status_code == 201, reservation.text[:200])
    if failures:
        return 1
    reservation = reservation.json()
    serial = http.post(f"{api}/sessions", json={"reservation_id": reservation["id"], "capability_type": "serial"}, headers=headers).json()
    power = http.post(f"{api}/sessions", json={"reservation_id": reservation["id"], "capability_type": "power"}, headers=headers).json()
    ws_url = args.hub.rstrip("/").replace("http", "ws", 1) + f"/api/v1/sessions/{serial['id']}/serial/ws"
    try:
        with connect(ws_url, open_timeout=10) as ws:
            ws.send(json.dumps({"type": "auth", "token": token}))
            check("console connects", json.loads(ws.recv(timeout=10)).get("type") == "ready")

            def collect(marker: str, seconds: float = 20) -> str:
                output, deadline = "", time.time() + seconds
                while marker not in output and time.time() < deadline:
                    try:
                        message = json.loads(ws.recv(timeout=2))
                    except TimeoutError:
                        continue
                    if message["type"] == "output":
                        output += message["data"]
                return output

            http.post(f"{api}/sessions/{power['id']}/execute", json={"operation": "off"}, headers=headers)
            result = http.post(f"{api}/sessions/{power['id']}/execute", json={"operation": "on"}, headers=headers).json()
            check("DD power on confirmed", bool(result.get("data", {}).get("confirmed")), result.get("message", ""))
            check("board boots on console", "board> " in collect("board> "))
            ws.send(json.dumps({"type": "input", "data": "version\r"}))
            check("console command round-trip", "firmware" in collect("firmware"))
            result = http.post(f"{api}/sessions/{power['id']}/execute", json={"operation": "reset"}, headers=headers).json()
            check("DD reset (power cycle)", "complete" in result.get("message", ""), result.get("message", ""))
            check("board reboots after reset", "U-Boot" in collect("board> "))
    finally:
        log = http.get(f"{api}/sessions/{serial['id']}/serial/log", headers=headers).text
        check("transcript stored", "U-Boot" in log, f"{len(log)} bytes")
        http.post(f"{api}/reservations/{reservation['id']}/release", headers=headers)
    print("ALL PASSED" if not failures else f"FAILED: {failures}")
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
