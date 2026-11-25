# TargetHub

> **One Platform. Every Target.**

TargetHub is an open-source **embedded lab orchestration platform**. It lets an engineering team share
hardware boards safely. Engineers reserve a board, get exclusive use of its serial console, power control
and firmware deployment, and release it when they are done. Everything works from the browser, the
`targethub` command line, the Python SDK, VS Code or a CI pipeline.

**Author:** Omkar Motaghare · **License:** Apache-2.0 · **Version:** 0.2.0 ([changelog](CHANGELOG.md))

> **Status:** 0.2.0 is feature-complete and covered by automated tests on Linux. The DD power driver,
> the Raspberry Pi and Windows agents, and real boards have been verified so far only against simulators.
> Before relying on it for a lab, run the [manual verification checklist](docs/MANUAL_VERIFICATION_CHECKLIST.md).

---

## Contents

- [TargetHub](#targethub)
  - [Contents](#contents)
  - [Features at a glance](#features-at-a-glance)
  - [Quick start (one command)](#quick-start-one-command)
    - [What you need](#what-you-need)
    - [Linux or macOS: run one script](#linux-or-macos-run-one-script)
    - [Windows](#windows)
    - [Check that it works](#check-that-it-works)
  - [First steps for an administrator](#first-steps-for-an-administrator)
  - [Connect hardware](#connect-hardware)
    - [Power through a DD server](#power-through-a-dd-server)
    - [Agent on a Raspberry Pi, Linux or Windows host](#agent-on-a-raspberry-pi-linux-or-windows-host)
  - [Using TargetHub, feature by feature](#using-targethub-feature-by-feature)
    - [Sign in and change your password](#sign-in-and-change-your-password)
    - [Find a board](#find-a-board)
    - [Reserve a board](#reserve-a-board)
    - [Manage your reservations](#manage-your-reservations)
    - [Use the serial console](#use-the-serial-console)
    - [Power the board](#power-the-board)
    - [Deploy firmware](#deploy-firmware)
    - [Notifications and the calendar](#notifications-and-the-calendar)
    - [Personal API tokens](#personal-api-tokens)
  - [Automation: CLI, SDK, VS Code and CI](#automation-cli-sdk-vs-code-and-ci)
  - [Operations: upgrade, backup, TLS](#operations-upgrade-backup-tls)
  - [Architecture](#architecture)
  - [Documentation index](#documentation-index)
  - [Repository layout](#repository-layout)
  - [Roadmap and contributing](#roadmap-and-contributing)

---

## Features at a glance

| Area | What it does |
| --- | --- |
| **Reservations** | See live availability and a calendar. Reserve now or at a later time, extend, release early, reserve any free board with a given tag, and join a **waitlist** that hands over the board automatically when it frees up. Policy controls maximum duration, advance booking and per-user limits. **Maintenance** mode takes a board out of service with a visible reason. |
| **Sessions** | Each reservation gives its owner exclusive sessions on the board's capabilities. A **browser serial console** (a real terminal over WebSocket) keeps output while you are away and saves full transcripts you can download. Power and firmware deploy run from the same session. |
| **Power** | Three backends: the **DD (Doordarshan) REST power system** called from the server (no agent needed), a generic **HTTP power controller** (any PDU or relay with a simple REST API), or relays and GPIO lines on an agent. Power on, off, cycle, reset and status. |
| **Firmware deploy** | Give an HTTPS artifact URL and its SHA-256. The agent verifies the checksum before running your configured flashing tool (for example `st-flash`, `openocd` or `esptool`). A mismatch is refused before anything is flashed. |
| **Agents** | One small Python file for **Linux, Raspberry Pi and Windows** hosts. Agents connect outward to the server (no inbound ports needed), so they work behind NAT. Serial ports, GPIO lines and flashing commands are declared in the agent's own config, so the server cannot make an agent open arbitrary devices or run arbitrary commands. |
| **Accounts** | Local accounts with three roles: **admin** (manages everything), **user** (reserves and uses boards) and **viewer** (read-only). Rotating sign-in tokens, personal API tokens for scripts and CI, rate-limited login, and an audit log of every change. |
| **Notifications** | An in-app bell, plus **Slack**, **Microsoft Teams** and generic webhooks. Generic webhooks are signed with HMAC-SHA256 so the receiver can verify them. |
| **Automation** | A Python SDK and `targethub` CLI, a VS Code extension, a REST API with interactive docs at `/docs`, and Prometheus metrics at `/metrics`. |
| **Operations** | Docker Compose install for Linux, macOS and Windows, optional HTTPS with Caddy, backup and restore scripts, an admin recovery command, and health endpoints for load balancers. |

Want to try everything without hardware? A **simulated lab** (a mock DD power server and a virtual board)
lets you run every feature. See [Simulators and demo lab](docs/development/simulators.md).

---

## Quick start (one command)

### What you need

- A Linux or macOS machine, or a Windows machine with Docker Desktop.
- **Docker** with the **Docker Compose v2** plugin (`docker compose version` must work).
- **curl** and **python3** on Linux and macOS (the setup script uses them to create the admin account).
- Free disk space for the Docker images, and a few minutes for the first build.

### Linux or macOS: run one script

```bash
git clone https://github.com/omkar-motaghare/TargetHub.git
cd TargetHub
scripts/setup.sh
```

The script:

1. Checks that Docker, Docker Compose and curl are available and that Docker is running.
2. Generates a `.env` file with random secrets (kept private, mode 600), then builds and starts the
   TargetHub server and its PostgreSQL database.
3. Waits until the server reports healthy.
4. Asks for an admin username and password and creates the first admin account.
5. Prints the address to open and the next steps.

Common variations:

```bash
scripts/setup.sh --admin-user alice                      # choose the admin username
scripts/setup.sh --port 8080                             # use another port
scripts/setup.sh --url http://lab-server.local:8080      # the address your team will use
scripts/setup.sh --domain hub.example.com                # HTTPS with automatic certificates (needs DNS and ports 80/443)
scripts/setup.sh --no-admin                              # skip the admin step and create it in the browser later
TARGETHUB_ADMIN_PASSWORD='choose-a-strong-one' scripts/setup.sh --admin-user alice   # non-interactive
```

Running the script again is safe. It reuses your existing `.env` and does not create a second admin.

### Windows

Windows uses the installer for the server stack. Run this in PowerShell from the TargetHub folder:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\install.ps1
```

It prints the URL and a one-time **bootstrap token**. Open the URL in a browser and create the first admin
with that token. The token is in `.env` as `ADMIN_BOOTSTRAP_TOKEN`.

### Check that it works

Open `http://<host>:8000/app` (or the address you chose), sign in as the admin, and open **Admin → Overview**.
The configuration check should show no errors. If it does not, the problems are listed there.

---

## First steps for an administrator

Everything in this section is under **Admin** in the web UI and requires the admin role.

1. **Add your boards.** Go to **Admin → Targets → Add target**. Give it a name, a lab, optional tags such as
   `stm32` or `rack-2`, and then add its capabilities (see [Connect hardware](#connect-hardware)).
2. **Add accounts.** Go to **Admin → Users**, create each person with a temporary password, and choose the
   role. Use **user** for engineers, **viewer** for managers and dashboards, and keep **admin** to a small group.
3. **Set the reservation policy.** Go to **Admin → Settings → Reservation policy**. The defaults are a 480-minute
   maximum, 60-minute default, 30-day advance booking and no per-user limit. Change them to suit your lab.
4. **Send notifications (optional).** Go to **Admin → Settings → Webhooks**, add a Slack, Teams or generic
   webhook, and press **Send test**.
5. **Check the configuration.** **Admin → Overview** lists anything that will stop users from working, such as
   an offline agent, a missing environment variable or a power capability without a driver.

---

## Connect hardware

A target's **capabilities** are what users can open in a session: serial console, power and deploy. Each
capability is backed by one of these options.

| Backend | Runs on | Use it for | Setup guide |
| --- | --- | --- | --- |
| **DD power system** | TargetHub server | Relay power control through a DD server. No agent needed. | [DD power](docs/power/dd-power.md) |
| **HTTP power controller** | TargetHub server | Any PDU or relay with a simple REST API. | [Administration](docs/admin-guide/administration.md#http-power-controller-contract) |
| **Agent hardware** | An agent host (Linux, Raspberry Pi, Windows) | Serial consoles, GPIO relays and deploy commands. | [Agent guide](docs/agents/agent-guide.md) |
| **Simulated** | Server | Demos only. Refused unless `ALLOW_SIMULATED_PROVIDERS=true`. | [Simulators](docs/development/simulators.md) |

### Power through a DD server

1. Add the DD API key to the server: `echo 'TARGETHUB_DD_API_KEY=<key>' >> .env`, then
   `docker compose up -d`. The key is never stored in the database or shown in the UI.
2. In **Admin → Targets**, edit the target and add a **Power** capability with backend **DD power system (server)**.
3. Fill in the DD server URL, hub MAC address, node ID, endpoint, and the name of the API key variable.
4. Click **Test connection**. It reads the status without switching anything.

### Agent on a Raspberry Pi, Linux or Windows host

1. In **Admin → Agents**, click **Create enrollment**. The token is single-use and valid for 30 minutes.
2. Run the install command shown for the host's platform (Linux and Raspberry Pi, or Windows).
3. Wait for the agent to appear as **online** (within about 15 seconds).
4. Edit the target, add a **Serial** or **Power** capability with backend **Agent hardware**, and choose the
   agent and the resource it reported (for example `/dev/serial/by-id/...` or `COM3`).

The agent's config file lists exactly which serial ports, GPIO lines and commands it may use. Check the
[agent guide](docs/agents/agent-guide.md) and [Raspberry Pi notes](docs/agents/raspberry-pi.md) for details.

---

## Using TargetHub, feature by feature

This is the day-to-day guide for engineers. The full version is in the
[user guide](docs/user-guide/using-targethub.md).

### Sign in and change your password

Your administrator gives you a username, a temporary password and the TargetHub address. Sign in and change
the password under **Account**. You can also sign out of every device there.

### Find a board

The **Targets** page shows each board's state: **Available**, **Reserved** (with who holds it and until when),
**Ending soon**, or **Maintenance** and **Retired** with a reason. Filter by tag or state. A capability marked
*simulated* has no real hardware behind it.

### Reserve a board

- **Reserve** for a specific board: choose a duration (or a later start time) and add a note so colleagues know
  what you are doing.
- **Reserve any with tag**: pick a tag such as `stm32`, and TargetHub assigns the first free board with it.
- **Join waitlist**: if the board is busy, you are queued. When it is released, you receive it automatically
  and get a notification. Waitlist entries expire after 24 hours by default.

### Manage your reservations

Open **Reservations** to:

- **Open a session** for a capability (serial, power or deploy).
- **Extend** the reservation, within the maximum duration. Extending can be blocked while others are waiting.
- **Release** the board as soon as you are finished, so the next person can use it.

A reservation ends automatically. You get an "ending soon" warning 10 minutes before by default. At the end
time, open sessions close and the serial port is released on the agent.

### Use the serial console

The console is a real terminal in the browser. Keystrokes go to the board, and paste works. Output that arrives
while you are away is kept and shown when you return. **Clear** clears the screen. **Download** saves the full
transcript with timestamps, and **Reconnect** re-attaches after a network drop. Transcripts are kept for 30 days
by default.

### Power the board

Use **Status**, **Power on**, **Power off**, **Power cycle** or **Reset**. For DD power, cycle and reset both mean
off, a short pause and on, because DD only switches power. The result says whether the device **confirmed** the
new state. If it says the command was accepted but not confirmed yet, check the status again before assuming the
board is off.

### Deploy firmware

Enter an HTTPS URL for the firmware file and its SHA-256 checksum. The agent downloads the file, verifies the
checksum and runs the flashing command configured for that board. The flashing tool's output is shown when the
job finishes. A wrong checksum is refused before anything is flashed.

### Notifications and the calendar

The bell in the header shows events such as a board becoming yours from the waitlist, an ending reservation, or an
admin releasing your board. Your team can receive the same events in Slack or Teams. The **Calendar** shows
everyone's bookings for the coming days so you can plan ahead.

### Personal API tokens

Under **Account**, create a token (`thp_...`) for scripts, the CLI, VS Code or CI. A token acts as you with your
role, is shown only once, can be revoked at any time, and should be one per machine or pipeline.

---

## Automation: CLI, SDK, VS Code and CI

```bash
pip install "targethub-sdk[console] @ git+https://github.com/omkar-motaghare/TargetHub#subdirectory=sdk/python"
export TARGETHUB_URL=https://hub.example.com
targethub login --username alice          # stores an API token on this machine
targethub targets --free
targethub reserve STM32-01 --minutes 60 --wait
targethub open <reservation-id> serial
targethub console <session-id>            # interactive console in your terminal
targethub release STM32-01
```

- **VS Code:** install the TargetHub extension, sign in with an API token, then use the *TargetHub: …* commands
  to reserve, open a console and release. See the [extension README](vscode-extension/README.md).
- **CI and hardware-in-the-loop:** reserve a board at the start of a job and release it at the end. See
  [CLI, SDK and CI](docs/automation/ci-hil.md).
- **REST API:** interactive documentation is at `/docs` on your server.
- **Metrics:** Prometheus metrics are at `/metrics` and require the `METRICS_TOKEN` from `.env`.

---

## Operations: upgrade, backup, TLS

| Task | Command or guide |
| --- | --- |
| Back up the database | `scripts/backup.sh backups/`. See [Backup and restore](docs/deployment/backup.md). |
| Restore a backup | `scripts/restore.sh --yes backups/<file>.dump` |
| Recover a lost admin password | `scripts/reset_admin_user.sh reset <user>` |
| Upgrade | Back up, then `git pull` and `scripts/install.sh`. Migrations run at startup. See [Upgrade and rollback](docs/operations/upgrade.md). |
| Enable HTTPS | `scripts/setup.sh --domain <name>` or `scripts/install.sh --domain <name>`. See [TLS](docs/deployment/tls.md). |
| Health checks | `GET /health/live` (process up) and `GET /health/ready` (database reachable). |
| Logs | `docker compose logs api`. Set `TARGETHUB_LOG_FORMAT=json` for log shippers. |
| Troubleshooting | [Troubleshooting guide](docs/operations/troubleshooting.md) |
| Security notes | [Security](docs/operations/security.md) |

Keep `.env` stable and backed up. Changing `SECRET_KEY` signs everyone out, so keep the same file across
restarts and upgrades.

---

## Architecture

```text
 Browser UI · VS Code · targethub CLI / Python SDK · CI jobs
                       │  HTTPS (REST + WebSocket)
              ┌────────┴─────────┐
              │ TargetHub server │  reservations, sessions, auth, policy, waitlist,
              │ FastAPI + React  │  notifications, audit, scheduler
              └──┬────────────┬──┘
   server-hosted │            │ outbound long-poll (no inbound ports on the agent)
   DD / HTTP power            │
        ┌────────┴──┐   ┌─────┴──────────────────────┐
        │ DD power  │   │ TargetHub Agent            │  Raspberry Pi / Linux / Windows
        │ system    │   │ serial · GPIO · deploy     │
        └───────────┘   └─────┬──────────────────────┘
                              │ USB-serial, GPIO, flashing tools
                        Embedded targets
```

More detail is in the [architecture overview](docs/architecture/overview.md).

---

## Documentation index

- **Getting started:** [Installation](docs/getting-started/install.md) (Linux, macOS, Windows, published image, TLS, without Docker)
- **Using the lab:** [User guide](docs/user-guide/using-targethub.md)
- **Administering the lab:** [Administration](docs/admin-guide/administration.md)
- **Hardware:** [Agents](docs/agents/agent-guide.md) · [Agent operations](docs/agents/agent-operations.md) · [Raspberry Pi](docs/agents/raspberry-pi.md) · [DD power](docs/power/dd-power.md)
- **Automation:** [CLI, SDK and CI](docs/automation/ci-hil.md) · [VS Code extension](vscode-extension/README.md)
- **Operations:** [Upgrade](docs/operations/upgrade.md) · [Backup](docs/deployment/backup.md) · [TLS](docs/deployment/tls.md) · [Troubleshooting](docs/operations/troubleshooting.md) · [Security](docs/operations/security.md)
- **Developers:** [Local development](docs/developer-guide/local-docker-development.md) · [Simulators and demo lab](docs/development/simulators.md) · [Architecture](docs/architecture/overview.md)
- **Verification:** [Manual verification checklist](docs/MANUAL_VERIFICATION_CHECKLIST.md)

To browse the documentation as a website: `pip install mkdocs-material && mkdocs serve`.

---

## Repository layout

```text
backend/            FastAPI server, Alembic migrations, tests; agent files in backend/app/web/agent/
frontend/           React web UI (built into the server image)
sdk/python/         Python SDK and the `targethub` CLI
vscode-extension/   VS Code extension
tools/              Mock DD server, virtual board, demo lab
scripts/            setup, install, backup and restore, admin recovery, end-to-end tests
docs/               Documentation (MkDocs)
```

---

## Roadmap and contributing

Planned after 0.2.0: SSH and Telnet proxying, J-Link debugging, artifact upload, richer health checks and
single sign-on. See the [roadmap](docs/development/ROADMAP.md).

Issues and pull requests are welcome. Run the test suites described in the
[development guide](docs/developer-guide/local-docker-development.md) before opening a pull request.
