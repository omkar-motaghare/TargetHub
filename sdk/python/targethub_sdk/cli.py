"""`targethub` command line client.

Configure with TARGETHUB_URL plus TARGETHUB_TOKEN (a personal API token from
Account -> API tokens, best for CI) or run `targethub login` once, which
creates an API token for this machine and stores it (mode 0600).
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
import socket
import sys
import threading
import time
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from targethub_sdk.client import TargetHubClient, TargetHubError

TOKEN_FILE = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "targethub" / "token"
POWER_OPERATIONS = ["on", "off", "status", "cycle", "reset"]
CONSOLE_ESCAPE = "\x1d"  # Ctrl+]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="targethub", description="TargetHub lab client")
    parser.add_argument("--url", default=os.environ.get("TARGETHUB_URL", "http://127.0.0.1:8000"))
    parser.add_argument("--ca-bundle", default=os.environ.get("TARGETHUB_CA_BUNDLE"))
    sub = parser.add_subparsers(dest="command", required=True)

    login = sub.add_parser("login", help="sign in and store an API token for this machine (0600)")
    login.add_argument("--username", required=True)
    login.add_argument("--password-stdin", action="store_true", help="read the password from stdin")
    login.add_argument("--expires-days", type=int, default=365)
    sub.add_parser("logout", help="revoke and forget the stored token")
    sub.add_parser("whoami", help="show the authenticated user")

    targets = sub.add_parser("targets", help="list targets with availability")
    targets.add_argument("--tag")
    targets.add_argument("--free", action="store_true", help="only targets available now")

    sub.add_parser("reservations", help="list your reservations")
    sub.add_parser("calendar", help="everyone's bookings for the next 7 days")

    reserve = sub.add_parser("reserve", help="reserve a target (by name or id) or any target with a tag")
    reserve.add_argument("target", nargs="?", help="target name or id")
    reserve.add_argument("--tag", help="reserve any free target carrying this tag")
    reserve.add_argument("--minutes", type=int, default=30)
    reserve.add_argument("--note")
    reserve.add_argument("--wait", action="store_true", help="if busy, join the waitlist and wait until granted")
    reserve.add_argument("--timeout", type=float, default=3600, help="seconds to wait with --wait")

    extend = sub.add_parser("extend", help="extend a reservation")
    extend.add_argument("reservation_id")
    extend.add_argument("--minutes", type=int, default=30)
    release = sub.add_parser("release", help="release a reservation (by id, or your reservation of a target)")
    release.add_argument("reservation")

    sub.add_parser("waitlist", help="list your waitlist entries")
    leave = sub.add_parser("leave", help="leave a waitlist entry")
    leave.add_argument("entry_id")

    sub.add_parser("sessions", help="list sessions")
    open_session = sub.add_parser("open", help="open a session on a reservation")
    open_session.add_argument("reservation_id")
    open_session.add_argument("capability_type")
    open_session.add_argument("--capability-id")
    close = sub.add_parser("close", help="close a session")
    close.add_argument("session_id")

    power = sub.add_parser("power", help="run a power operation")
    power.add_argument("session_id")
    power.add_argument("operation", choices=POWER_OPERATIONS)

    serial = sub.add_parser("serial", help="send a line to a serial session and print what comes back")
    serial.add_argument("session_id")
    serial.add_argument("--send", default="", help="text to write (a newline is appended)")
    serial.add_argument("--expect", help="read until this text appears (exit 1 if it does not)")
    serial.add_argument("--wait", type=float, default=2.0, help="seconds to read (or the --expect timeout)")

    console = sub.add_parser("console", help="interactive serial console (needs: pip install websockets)")
    console.add_argument("session_id")

    log = sub.add_parser("log", help="download a serial session transcript")
    log.add_argument("session_id")
    log.add_argument("--include-input", action="store_true")

    deploy = sub.add_parser("deploy", help="deploy a checksummed artifact through the Agent")
    deploy.add_argument("session_id")
    deploy.add_argument("url")
    deploy.add_argument("sha256")
    deploy.add_argument("--no-wait", action="store_true", help="return immediately with the operation id")
    deploy.add_argument("--timeout", type=float, default=900)

    token = sub.add_parser("token", help="manage personal API tokens")
    token_sub = token.add_subparsers(dest="token_command", required=True)
    token_create = token_sub.add_parser("create")
    token_create.add_argument("name")
    token_create.add_argument("--expires-days", type=int)
    token_sub.add_parser("list")
    token_revoke = token_sub.add_parser("revoke")
    token_revoke.add_argument("token_id")

    sub.add_parser("notifications", help="your notifications")
    sub.add_parser("agents", help="list agents (admin)")
    enroll = sub.add_parser("enroll", help="create an agent enrollment (admin)")
    enroll.add_argument("agent_name")
    audit = sub.add_parser("audit", help="query the audit log (admin)")
    audit.add_argument("--user-id")
    audit.add_argument("--target-id")
    audit.add_argument("--action")
    audit.add_argument("--limit", type=int, default=50)
    return parser


def stored_token() -> str | None:
    if os.environ.get("TARGETHUB_TOKEN"):
        return os.environ["TARGETHUB_TOKEN"]
    if TOKEN_FILE.exists():
        return TOKEN_FILE.read_text().strip() or None
    return None


def save_token(token: str) -> None:
    TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor = os.open(TOKEN_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w") as handle:
        handle.write(token)


def emit(value: Any) -> None:
    sys.stdout.write(json.dumps(value, indent=2, sort_keys=True) + "\n")


def run_serial(client: TargetHubClient, session_id: str, send: str, wait: float, expect: str | None = None) -> str:
    client.serial_open(session_id)
    if send:
        client.serial_write(session_id, send + "\n")
    if expect:
        return client.serial_expect(session_id, expect, timeout=wait)
    deadline = time.monotonic() + wait
    received = ""
    while time.monotonic() < deadline:
        remaining_ms = int(max(0.0, deadline - time.monotonic()) * 1000)
        received += client.serial_read(session_id, size=65536, wait_ms=min(remaining_ms, 2000))
    return received


def run_console(client: TargetHubClient, session_id: str) -> int:  # pragma: no cover - interactive
    try:
        from websockets.sync.client import connect
    except ImportError:
        sys.stderr.write("error: the console needs the websockets package: pip install websockets\n")
        return 1
    url = client.serial_ws_url(session_id)
    sys.stderr.write(f"Connecting to {url} (press Ctrl+] to exit)\n")
    with connect(url, open_timeout=15) as ws:
        ws.send(json.dumps({"type": "auth", "token": client.token}))
        ready = json.loads(ws.recv(timeout=15))
        if ready.get("type") != "ready":
            sys.stderr.write(f"error: {ready.get('reason', ready)}\n")
            return 1
        stop = threading.Event()

        def pump_output() -> None:
            while not stop.is_set():
                try:
                    message = json.loads(ws.recv(timeout=1))
                except TimeoutError:
                    continue
                except Exception:  # noqa: BLE001 - socket closed
                    stop.set()
                    return
                if message["type"] == "output":
                    sys.stdout.write(message["data"])
                    sys.stdout.flush()
                elif message["type"] == "notice":
                    sys.stderr.write(f"\r\n[targethub] {message['message']}\r\n")
                elif message["type"] == "closed":
                    sys.stderr.write(f"\r\n[targethub] {message.get('reason')}\r\n")
                    stop.set()

        threading.Thread(target=pump_output, daemon=True).start()
        for char in _raw_keys(stop):
            if char == CONSOLE_ESCAPE:
                break
            ws.send(json.dumps({"type": "input", "data": char}))
        stop.set()
    return 0


def _raw_keys(stop: threading.Event):  # pragma: no cover - interactive
    if os.name == "nt":
        import msvcrt

        while not stop.is_set():
            if msvcrt.kbhit():
                yield msvcrt.getwch()
            else:
                time.sleep(0.02)
        return
    import select
    import termios
    import tty

    fd = sys.stdin.fileno()
    previous = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        while not stop.is_set():
            readable, _, _ = select.select([fd], [], [], 0.2)
            if readable:
                yield os.read(fd, 1024).decode("utf-8", errors="replace")
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, previous)


def _release(client: TargetHubClient, reservation: str) -> dict[str, Any]:
    active = client.list_reservations(status="active")
    if any(item["id"] == reservation for item in active):
        return client.release_reservation(reservation)
    target = client.find_target(reservation)
    mine = [item for item in active if item["target_id"] == target["id"]]
    if not mine:
        raise TargetHubError(404, f"You have no active reservation of {target['name']}")
    return client.release_reservation(mine[0]["id"])


def _reserve(client: TargetHubClient, args: argparse.Namespace) -> dict[str, Any]:
    if bool(args.target) == bool(args.tag):
        raise TargetHubError(2, "give a target name/id or --tag (not both)")
    try:
        if args.tag:
            return client.reserve_any(args.tag, args.minutes, args.note)
        return client.reserve(args.target, args.minutes, args.note)
    except TargetHubError as error:
        if not args.wait or error.status_code != 409 or "policy" in error.detail.lower():
            raise
    sys.stderr.write("busy; waiting in the queue...\n")
    target_id = client.find_target(args.target)["id"] if args.target else None
    return client.wait_for_reservation(
        target_id=target_id, tag=args.tag, minutes=args.minutes, timeout=args.timeout, note=args.note
    )


def dispatch(client: TargetHubClient, args: argparse.Namespace) -> int:
    command = args.command
    if command == "whoami":
        emit(client.me())
    elif command == "targets":
        rows = client.list_targets(args.tag)
        if args.free:
            rows = [row for row in rows if (row.get("availability") or {}).get("state") == "available"]
        emit(rows)
    elif command == "reservations":
        emit(client.list_reservations())
    elif command == "calendar":
        emit(client.calendar())
    elif command == "reserve":
        emit(_reserve(client, args))
    elif command == "extend":
        emit(client.extend_reservation(args.reservation_id, args.minutes))
    elif command == "release":
        emit(_release(client, args.reservation))
    elif command == "waitlist":
        emit(client.list_waitlist())
    elif command == "leave":
        emit(client.leave_waitlist(args.entry_id))
    elif command == "sessions":
        emit(client.list_sessions())
    elif command == "open":
        emit(client.open_session(args.reservation_id, args.capability_type, args.capability_id))
    elif command == "close":
        emit(client.close_session(args.session_id))
    elif command == "power":
        emit(client.power(args.session_id, args.operation))
    elif command == "serial":
        sys.stdout.write(run_serial(client, args.session_id, args.send, args.wait, args.expect))
    elif command == "console":
        return run_console(client, args.session_id)
    elif command == "log":
        sys.stdout.write(client.serial_log(args.session_id, args.include_input))
    elif command == "deploy":
        emit(client.deploy(args.session_id, args.url, args.sha256, wait=not args.no_wait, timeout=args.timeout))
    elif command == "token":
        if args.token_command == "create":
            emit(client.create_api_token(args.name, args.expires_days))
        elif args.token_command == "list":
            emit(client.list_api_tokens())
        else:
            client.revoke_api_token(args.token_id)
            emit({"revoked": args.token_id})
    elif command == "notifications":
        emit(client.notifications())
    elif command == "agents":
        emit(client.list_agents())
    elif command == "enroll":
        emit(client.create_enrollment(args.agent_name))
    elif command == "audit":
        filters = {
            key: value
            for key, value in {
                "user_id": args.user_id,
                "target_id": args.target_id,
                "action": args.action,
                "limit": args.limit,
            }.items()
            if value
        }
        emit(client.audit(**filters))
    return 0


def main(
    argv: Sequence[str] | None = None,
    client_factory: Callable[..., TargetHubClient] = TargetHubClient,
) -> int:
    args = build_parser().parse_args(argv)
    verify: bool | str = args.ca_bundle or True
    client = client_factory(args.url, stored_token(), verify=verify)
    try:
        if args.command == "login":
            password = sys.stdin.readline().rstrip("\n") if args.password_stdin else getpass.getpass()
            client.login(args.username, password)
            # A long-lived personal token, so scripts keep working after the 15-minute access token expires.
            created = client.create_api_token(f"cli@{socket.gethostname()}"[:100], args.expires_days)
            save_token(created["token"])
            sys.stdout.write(f"logged in as {args.username}; API token {created['prefix']}… stored in {TOKEN_FILE}\n")
            return 0
        if args.command == "logout":
            token = stored_token()
            if token and token.startswith("thp_"):
                prefix = token[:12]
                for item in client.list_api_tokens():
                    if item["prefix"] == prefix and not item.get("revoked_at"):
                        client.revoke_api_token(item["id"])
            if TOKEN_FILE.exists():
                TOKEN_FILE.unlink()
            sys.stdout.write("logged out\n")
            return 0
        return dispatch(client, args)
    except TargetHubError as error:
        sys.stderr.write(f"error: {error.detail if error.status_code == 2 else error}\n")
        return 1
    finally:
        client.close()


if __name__ == "__main__":
    raise SystemExit(main())
