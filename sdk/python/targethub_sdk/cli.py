"""`targethub` command line client. Configure with TARGETHUB_URL and TARGETHUB_TOKEN or `targethub login`."""

from __future__ import annotations

import argparse
import getpass
import json
import os
import sys
import time
from collections.abc import Callable, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from targethub_sdk.client import TargetHubClient, TargetHubError

TOKEN_FILE = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "targethub" / "token"
POWER_OPERATIONS = ["on", "off", "status", "cycle", "reset"]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="targethub", description="TargetHub lab client")
    parser.add_argument("--url", default=os.environ.get("TARGETHUB_URL", "http://127.0.0.1:8000"))
    parser.add_argument("--ca-bundle", default=os.environ.get("TARGETHUB_CA_BUNDLE"))
    sub = parser.add_subparsers(dest="command", required=True)

    login = sub.add_parser("login", help="authenticate and store a token (mode 0600)")
    login.add_argument("--username", required=True)
    login.add_argument("--password-stdin", action="store_true", help="read the password from stdin")

    sub.add_parser("targets", help="list targets")
    sub.add_parser("reservations", help="list reservations")
    reserve = sub.add_parser("reserve", help="reserve a target starting now")
    reserve.add_argument("target_id")
    reserve.add_argument("--minutes", type=int, default=30)
    release = sub.add_parser("release", help="release a reservation")
    release.add_argument("reservation_id")

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

    serial = sub.add_parser("serial", help="send a line to a serial session and print the reply")
    serial.add_argument("session_id")
    serial.add_argument("--send", default="", help="text to write (a newline is appended)")
    serial.add_argument("--wait", type=float, default=2.0, help="seconds to keep reading")

    deploy = sub.add_parser("deploy", help="deploy a checksummed artifact")
    deploy.add_argument("session_id")
    deploy.add_argument("url")
    deploy.add_argument("sha256")

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


def run_serial(client: TargetHubClient, session_id: str, send: str, wait: float) -> str:
    client.serial_open(session_id)
    if send:
        client.serial_write(session_id, send + "\n")
    deadline = time.monotonic() + wait
    received = ""
    while time.monotonic() < deadline:
        received += client.serial_read(session_id)
        time.sleep(0.2)
    return received


def dispatch(client: TargetHubClient, args: argparse.Namespace) -> None:
    command = args.command
    if command == "targets":
        emit(client.list_targets())
    elif command == "reservations":
        emit(client.list_reservations())
    elif command == "reserve":
        now = datetime.now(UTC)
        emit(
            client.create_reservation(
                args.target_id, now.isoformat(), (now + timedelta(minutes=args.minutes)).isoformat()
            )
        )
    elif command == "release":
        emit(client.release_reservation(args.reservation_id))
    elif command == "sessions":
        emit(client.list_sessions())
    elif command == "open":
        emit(client.open_session(args.reservation_id, args.capability_type, args.capability_id))
    elif command == "close":
        emit(client.close_session(args.session_id))
    elif command == "power":
        emit(client.power(args.session_id, args.operation))
    elif command == "serial":
        sys.stdout.write(run_serial(client, args.session_id, args.send, args.wait))
    elif command == "deploy":
        emit(client.deploy(args.session_id, args.url, args.sha256))
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
            save_token(client.login(args.username, password))
            sys.stdout.write(f"logged in as {args.username}\n")
            return 0
        dispatch(client, args)
        return 0
    except TargetHubError as error:
        sys.stderr.write(f"error: {error}\n")
        return 1
    finally:
        client.close()


if __name__ == "__main__":
    raise SystemExit(main())
