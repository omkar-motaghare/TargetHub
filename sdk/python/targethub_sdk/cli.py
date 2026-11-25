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

    teams = sub.add_parser("teams", help="list your teams (all teams with --all, admin only)")
    teams.add_argument("--all", action="store_true")

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

    tunnel = sub.add_parser(
        "tunnel",
        help="forward a local port (or stdio) to the board's SSH/Telnet/GDB service (needs: pip install websockets)",
    )
    tunnel.add_argument("session_id", help="id of a session on a 'tunnel' capability")
    tunnel.add_argument("--local-port", type=int, default=0, help="local port to listen on (default: pick a free one)")
    tunnel.add_argument("--stdio", action="store_true", help="relay stdin/stdout instead (for ssh ProxyCommand)")

    log = sub.add_parser("log", help="download a serial session transcript")
    log.add_argument("session_id")
    log.add_argument("--include-input", action="store_true")

    deploy = sub.add_parser(
        "deploy",
        help="deploy firmware: URL + SHA-256, an uploaded artifact (--artifact-id) or a local file (--file)",
    )
    deploy.add_argument("session_id")
    deploy.add_argument("url", nargs="?")
    deploy.add_argument("sha256", nargs="?")
    deploy.add_argument("--artifact-id", help="id of an artifact uploaded to the server")
    deploy.add_argument("--file", help="upload this local file first, then deploy it")
    deploy.add_argument("--no-wait", action="store_true", help="return immediately with the operation id")
    deploy.add_argument("--timeout", type=float, default=900)

    artifact = sub.add_parser("artifact", help="firmware artifacts stored on the server")
    artifact_sub = artifact.add_subparsers(dest="artifact_command", required=True)
    artifact_upload = artifact_sub.add_parser("upload", help="upload a firmware file")
    artifact_upload.add_argument("path")
    artifact_upload.add_argument("--description")
    artifact_list = artifact_sub.add_parser("list", help="list uploaded artifacts")
    artifact_list.add_argument("--mine", action="store_true")
    artifact_delete = artifact_sub.add_parser("delete", help="delete an artifact you uploaded")
    artifact_delete.add_argument("artifact_id")

    report = sub.add_parser("report", help="usage report: utilisation, idle reservations, waitlist (admin)")
    report.add_argument("--days", type=int, default=30, help="period ending now (default 30)")
    report.add_argument(
        "--csv",
        choices=["targets", "tags", "users", "teams", "idle", "waitlist"],
        help="print this table as CSV instead of the JSON summary",
    )

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


def _connect_tunnel(client: TargetHubClient, session_id: str):
    """Open and authenticate a tunnel WebSocket; returns it, or raises RuntimeError."""
    from websockets.sync.client import connect

    ws = connect(client.tunnel_ws_url(session_id), open_timeout=15, max_size=None)
    ws.send(json.dumps({"type": "auth", "token": client.token}))
    ready = json.loads(ws.recv(timeout=30))
    if ready.get("type") != "ready":
        ws.close()
        raise RuntimeError(str(ready.get("reason", ready)))
    return ws


def relay(ws: Any, read_local: Callable[[], bytes], write_local: Callable[[bytes], None], log: Callable[[str], None]) -> None:
    """Copy bytes between the tunnel WebSocket and a local endpoint until either side ends."""
    stop = threading.Event()

    def from_board() -> None:
        while not stop.is_set():
            try:
                message = ws.recv(timeout=1)
            except TimeoutError:
                continue
            except Exception:  # noqa: BLE001 - socket closed
                break
            if isinstance(message, bytes):
                try:
                    write_local(message)
                except OSError:
                    break
                continue
            info = json.loads(message)
            if info.get("type") == "notice":
                log(f"[targethub] {info['message']}")
            elif info.get("type") == "closed":
                log(f"[targethub] {info.get('reason')}")
                break
        stop.set()

    def from_local() -> None:
        try:
            while not stop.is_set():
                data = read_local()
                if not data:
                    break
                ws.send(data)
        except Exception:  # noqa: BLE001 - local endpoint or socket closed
            pass
        stop.set()

    threads = [threading.Thread(target=from_board, daemon=True), threading.Thread(target=from_local, daemon=True)]
    for thread in threads:
        thread.start()
    stop.wait()
    try:
        ws.close()
    except Exception:  # noqa: BLE001 - best effort
        pass
    threads[0].join(timeout=3)  # the local reader unblocks when its endpoint is closed by the caller


def run_tunnel(client: TargetHubClient, session_id: str, local_port: int, stdio: bool) -> int:  # pragma: no cover - interactive
    try:
        import websockets.sync.client  # noqa: F401
    except ImportError:
        sys.stderr.write("error: the tunnel needs the websockets package: pip install websockets\n")
        return 1

    def log(text: str) -> None:
        sys.stderr.write(text + "\n")

    if stdio:
        try:
            ws = _connect_tunnel(client, session_id)
        except Exception as exc:  # noqa: BLE001
            log(f"error: {exc}")
            return 1
        stdin, stdout = sys.stdin.buffer, sys.stdout.buffer

        def write_out(data: bytes) -> None:
            stdout.write(data)
            stdout.flush()

        relay(ws, lambda: os.read(stdin.fileno(), 65536), write_out, lambda _t: None)
        return 0

    listener = socket.socket()
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(("127.0.0.1", local_port))
    listener.listen(1)
    port = listener.getsockname()[1]
    log(f"Tunnel ready on 127.0.0.1:{port}. Example: ssh -p {port} user@127.0.0.1  or  target remote :{port}. Ctrl+C to stop.")
    try:
        while True:
            conn, _addr = listener.accept()
            try:
                ws = _connect_tunnel(client, session_id)
            except Exception as exc:  # noqa: BLE001
                log(f"error: {exc}")
                conn.close()
                return 1
            with conn:
                relay(ws, lambda: conn.recv(65536), conn.sendall, log)
            log("[targethub] connection ended; waiting for the next one")
    except KeyboardInterrupt:
        return 0
    finally:
        listener.close()


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
    elif command == "teams":
        emit(client.list_teams() if args.all else client.my_teams())
    elif command == "tunnel":
        return run_tunnel(client, args.session_id, args.local_port, args.stdio)
    elif command == "log":
        sys.stdout.write(client.serial_log(args.session_id, args.include_input))
    elif command == "deploy":
        artifact_id = args.artifact_id
        if args.file:
            artifact_id = client.upload_artifact(args.file)["id"]
        if not artifact_id and not (args.url and args.sha256):
            print("deploy needs --file, --artifact-id, or both URL and SHA-256", file=sys.stderr)
            return 2
        emit(
            client.deploy(
                args.session_id,
                args.url,
                args.sha256,
                wait=not args.no_wait,
                timeout=args.timeout,
                artifact_id=artifact_id,
            )
        )
    elif command == "report":
        if args.csv:
            sys.stdout.write(client.usage_report_csv(args.csv, args.days))
        else:
            emit(client.usage_report(args.days))
    elif command == "artifact":
        if args.artifact_command == "upload":
            emit(client.upload_artifact(args.path, args.description))
        elif args.artifact_command == "list":
            emit(client.list_artifacts(mine=args.mine))
        else:
            client.delete_artifact(args.artifact_id)
            emit({"deleted": args.artifact_id})
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
