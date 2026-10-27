#!/usr/bin/env python3
"""Virtual embedded board on a pseudo-terminal (Linux, macOS, Raspberry Pi).

Creates a pty and (optionally) a stable symlink to it, e.g. /tmp/ttyVBOARD0,
that the TargetHub Agent can expose as a serial resource. The board:

  * prints a boot log when it powers on, then a ``board>`` shell prompt;
  * answers ``help``, ``version``, ``uptime``, ``echo <text>``, ``reboot``;
  * echoes anything else back as ``ECHO:<line>``;
  * optionally follows a DD power endpoint (real or the mock server): it goes
    silent while the relay is OFF and boots again when it turns ON, so a power
    cycle from TargetHub is visible on the serial console.

  python virtual_board.py --link /tmp/ttyVBOARD0
  python virtual_board.py --link /tmp/ttyVBOARD0 --dd-url http://localhost:5003 \\
      --hub-mac AA:BB:CC:DD:EE:FF --node 1 --endpoint 2

On Windows use the Agent's built-in ``sim://`` serial resources instead, or a
com0com virtual null-modem pair.
"""

from __future__ import annotations

import argparse
import json
import os
import select
import sys
import time
import urllib.parse
import urllib.request

if sys.platform.startswith("win"):  # pragma: no cover
    sys.exit("virtual_board.py needs a POSIX pty; on Windows use sim:// resources or com0com")

import pty
import tty

BOOT_LOG = [
    "",
    "U-Boot 2026.07 (TargetHub virtual board)",
    "DRAM:  512 MiB",
    "Starting kernel ...",
    "[    0.000000] Booting Linux on physical CPU 0x0",
    "[    0.120000] Machine model: TargetHub Virtual Board",
    "[    1.004000] Run /sbin/init as init process",
    "Welcome to TargetHub VirtualOS",
]


class Board:
    def __init__(self, master: int, name: str):
        self.master = master
        self.name = name
        self.powered = False
        self.booted_at = 0.0
        self.line = ""

    def write(self, text: str) -> None:
        try:
            os.write(self.master, text.replace("\n", "\r\n").encode("utf-8"))
        except OSError:
            pass

    def power(self, on: bool) -> None:
        if on and not self.powered:
            self.powered = True
            self.booted_at = time.monotonic()
            for line in BOOT_LOG:
                self.write(line + "\n")
                time.sleep(0.05)
            self.write("board> ")
        elif not on and self.powered:
            self.powered = False
            self.line = ""

    def feed(self, data: bytes) -> None:
        if not self.powered:
            return  # a powered-off board ignores input
        for char in data.decode("utf-8", errors="replace"):
            if char in "\r\n":
                command, self.line = self.line.strip(), ""
                self.write("\n")
                if command:
                    self.respond(command)
                self.write("board> ")
            elif char in "\x7f\b":
                if self.line:
                    self.line = self.line[:-1]
                    self.write("\b \b")
            elif char == "\x03":
                self.line = ""
                self.write("^C\nboard> ")
            else:
                self.line += char
                self.write(char)

    def respond(self, command: str) -> None:
        name, _, rest = command.partition(" ")
        if name == "help":
            self.write("commands: help, version, uptime, echo <text>, reboot\n")
        elif name == "version":
            self.write(f"{self.name} firmware 1.0.0\n")
        elif name == "uptime":
            self.write(f"up {time.monotonic() - self.booted_at:.1f}s\n")
        elif name == "echo":
            self.write(rest + "\n")
        elif name == "reboot":
            self.write("rebooting...\n")
            self.powered = False
            self.power(True)
        else:
            self.write(f"ECHO:{command}\n")


def dd_state(url: str, hub_mac: str, node: int, endpoint: int, api_key: str | None) -> bool | None:
    path = f"/api/hubs/{urllib.parse.quote(hub_mac, safe='')}/nodes/{node}/endpoints/{endpoint}"
    request = urllib.request.Request(url.rstrip("/") + path, headers={"X-API-Key": api_key} if api_key else {})
    try:
        with urllib.request.urlopen(request, timeout=3) as response:
            payload = json.loads(response.read().decode("utf-8"))
        return str(payload["endpoint"]["current_state"]).upper() == "ON"
    except Exception:  # noqa: BLE001 - keep running while DD is unreachable
        return None


def main() -> int:
    parser = argparse.ArgumentParser(description="Virtual board on a pty")
    parser.add_argument("--name", default="vboard-01")
    parser.add_argument("--link", help="create this symlink to the pty (e.g. /tmp/ttyVBOARD0)")
    parser.add_argument("--dd-url", help="follow this DD power endpoint")
    parser.add_argument("--hub-mac", default="AA:BB:CC:DD:EE:FF")
    parser.add_argument("--node", type=int, default=1)
    parser.add_argument("--endpoint", type=int, default=1)
    parser.add_argument("--api-key", default=os.environ.get("DD_API_KEY"))
    args = parser.parse_args()

    master, slave = pty.openpty()
    tty.setraw(slave)  # no echo or line editing on the device side
    path = os.ttyname(slave)
    if args.link:
        if os.path.lexists(args.link):
            os.unlink(args.link)
        os.symlink(path, args.link)
    print(f"virtual board '{args.name}' on {path}" + (f" (link {args.link})" if args.link else ""), flush=True)

    board = Board(master, args.name)
    if not args.dd_url:
        board.power(True)
    next_poll = 0.0
    try:
        while True:
            readable, _, _ = select.select([master], [], [], 0.2)
            if readable:
                try:
                    board.feed(os.read(master, 4096))
                except OSError:
                    time.sleep(0.2)
            if args.dd_url and time.monotonic() >= next_poll:
                next_poll = time.monotonic() + 0.5
                state = dd_state(args.dd_url, args.hub_mac, args.node, args.endpoint, args.api_key)
                if state is not None:
                    board.power(state)
    except KeyboardInterrupt:
        pass
    finally:
        if args.link and os.path.islink(args.link):
            os.unlink(args.link)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
