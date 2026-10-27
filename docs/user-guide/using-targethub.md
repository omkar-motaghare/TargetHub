# Using TargetHub

This guide is for engineers who use the lab. Your administrator gives you a username, a temporary password
and the TargetHub URL. After your first sign-in, change the password under **Account**.

## Roles

| Role | Can |
| --- | --- |
| **viewer** | See targets, availability and the calendar. Cannot reserve. |
| **user** | Everything a viewer can, plus reserve, join waitlists, open sessions and use consoles, power and deploy on **their own** reservations. |
| **admin** | Everything, plus manage targets, agents, users, policy, webhooks; force-release any reservation; read the audit log. |

## Finding a board: Targets

The **Targets** page shows every board with a live state:

- **Available**: free now.
- **Reserved**: someone has it; you see who and until when, and how many people are waiting.
- **Ending soon**: the current reservation ends within the warning window.
- **Maintenance** / **Retired**: an admin has taken it out of service (the reason is shown).

Filter by **tag** (for example `stm32`, `rack-2`, `nightly`) or by state. Each card lists its capabilities
(serial, power, deploy). A capability marked *simulated* has no real hardware behind it.

## Reserving

- **Reserve**: choose a duration (or a later start time, up to the policy's advance-booking limit) and an
  optional note so colleagues know what you are doing.
- **Reserve any with tag**: when you just need "an STM32 board", pick a tag and TargetHub gives you the
  first free target that has it.
- **Join waitlist**: if the board is busy, join the queue. When it is released, the first person in line
  gets the reservation automatically and a notification. Waitlist entries expire after the policy's
  waitlist lifetime (24 h by default).

Your administrator's **policy** may limit the maximum duration, how far ahead you can book and how many
reservations you can hold at once. The reserve dialog tells you the limits.

## My reservations

From **Reservations** you can:

- **Open a session** for a capability (serial console, power, deploy).
- **Extend** your reservation, within the maximum duration. If others are waiting, extending may be
  blocked by policy so the board is not held indefinitely.
- **Release** the board as soon as you are done; the next person in the waitlist gets it.
- See and leave your **waitlist** entries.

A reservation ends automatically at its end time. You receive an "ending soon" notification beforehand
(10 minutes by default). When it ends, open sessions are closed and serial ports released on the agent.

## Sessions

A session is your exclusive handle on one capability of a reserved target. Only the reservation owner
can open or use it.

### Serial console

The console is a real terminal in your browser (keyboard input goes straight to the board; paste works).

- Output that arrives while you are not looking is buffered and appears when you return.
- **Clear** clears the screen, **Download** saves the full transcript (input and output, timestamped on the
  server), **Reconnect** re-attaches after a network drop.
- Transcripts are kept for the policy's retention period (30 days by default) and are also available
  from the session page later.

### Power

**Power on / off / cycle / status**. Disruptive operations ask for confirmation. With a DD power system,
*cycle* and *reset* both mean OFF, wait a few seconds, ON (DD only switches power; there is no reset
line). The result says whether the device **confirmed** the new state. *Accepted, not confirmed yet*
means the DD server published the command but the relay has not reported back. Check status again before
assuming the board is off.

### Deploy firmware

Give an artifact URL (HTTPS) and its SHA-256. The agent downloads it, verifies the checksum and runs the
flashing command the administrator configured for that board. The output of the flashing tool is shown
when it finishes. Long deployments run in the background; the page polls until they are done.

## Notifications

The bell in the header shows reservation granted (from the waitlist), ending soon, expired, released by an
admin and similar events. Your team may also receive them in Slack or Teams.

## Calendar

**Calendar** shows everyone's bookings for the coming days, so you can plan a later reservation.

## Account and API tokens

**Account** (click your name) lets you change your password, sign out everywhere, and create **personal
API tokens** (`thp_…`) for scripts, the CLI, VS Code and CI. A token acts as you with your role; it is
shown once, can expire, and can be revoked at any time. Prefer a token per machine or pipeline.

## Command line and VS Code

```bash
pip install "targethub-sdk[console] @ git+https://github.com/omkar-motaghare/TargetHub#subdirectory=sdk/python"
export TARGETHUB_URL=https://hub.example.com
targethub login --username alice          # stores an API token for this machine
targethub targets --free
targethub reserve STM32-01 --minutes 60 --wait
targethub open <reservation-id> serial
targethub console <session-id>            # interactive console in your terminal
targethub release STM32-01
```

The VS Code extension has the same workflow from the command palette (*TargetHub: …*). See
[CLI, SDK and CI](../automation/ci-hil.md) and the [extension README](https://github.com/omkar-motaghare/TargetHub/tree/develop/vscode-extension).

## Etiquette that keeps a shared lab working

- Reserve for what you need, write a note, release early.
- Use tags and *reserve any* instead of always grabbing the same board.
- Never unplug or rewire a board that is reserved by someone else; ask the admin to put it in maintenance.
