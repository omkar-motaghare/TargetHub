# TargetHub

> **One Platform. Every Target.**

TargetHub is an open-source **embedded lab orchestration platform**. It lets an engineering team share
boards safely: reserve a target, get exclusive access to its serial console, power and firmware deploy,
and give it back, from a browser, the CLI, the Python SDK, VS Code or a CI pipeline.

**Author:** Omkar Motaghare · **License:** Apache-2.0 · **Version:** 0.2.0 ([changelog](CHANGELOG.md))

---

## What you get

| Area | Features |
| --- | --- |
| Reservations | Live availability, calendar, reserve now or later, extend, release, **reserve any free board by tag**, **waitlist** that auto-assigns the board when it frees up, per-team policy (max duration, advance booking, per-user limits), maintenance mode |
| Sessions | Exclusive, owner-only sessions; **browser serial console** (WebSocket, xterm.js) with full transcripts you can download; power on/off/cycle/status; checksummed firmware deploy |
| Power | **DD (Doordarshan) REST power system** run from the server, generic HTTP power controllers, or relays/GPIO on an Agent |
| Agents | One small Python file for **Linux, Raspberry Pi and Windows** hosts; outbound-only (works behind NAT); serial ports, GPIO relays and deploy commands declared locally on the agent |
| Accounts | Local accounts, roles **admin / user / viewer**, rotating refresh tokens, personal API tokens for CI, rate-limited login, audit log |
| Notifications | In-app bell plus Slack, Microsoft Teams and generic (HMAC-signed) webhooks |
| Automation | Python SDK + `targethub` CLI, VS Code extension, REST API with OpenAPI docs at `/docs`, Prometheus `/metrics` |
| Operations | Docker Compose (PostgreSQL) install for Linux and Windows, TLS overlay, backup/restore, admin recovery CLI, health checks |

No hardware yet? A **simulated lab** (mock DD power server + virtual board) lets you try every feature;
see [Simulators and demo lab](docs/development/simulators.md).

## Quick start

Requirements: Docker with the compose v2 plugin (Docker Desktop on Windows/macOS).

```bash
git clone https://github.com/omkar-motaghare/TargetHub.git && cd TargetHub
scripts/install.sh                     # Linux / macOS
```

```powershell
git clone https://github.com/omkar-motaghare/TargetHub.git; cd TargetHub
powershell -ExecutionPolicy Bypass -File scripts\install.ps1   # Windows
```

The installer writes `.env` with random secrets, starts PostgreSQL and the TargetHub server, and prints
the URL plus a one-time **bootstrap token**. Open the URL, create the first admin with that token, then:

1. **Admin → Targets**: add a board and its capabilities (serial, power, deploy).
2. Either add **DD power** directly (no agent needed), or **Admin → Agents** → create an enrollment and
   run the printed command on the Raspberry Pi / Linux / Windows machine the board is plugged into.
3. **Admin → Users**: invite your team (role *user*, or *viewer* for read-only).

Full instructions: [Installation](docs/getting-started/install.md).

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
        │ DD power  │   │ TargetHub Agent             │  Raspberry Pi / Linux / Windows
        │ system    │   │ serial · GPIO relay · deploy│
        └───────────┘   └─────┬──────────────────────┘
                              │ USB-serial, GPIO, flashing tools
                        Embedded targets
```

Read more in [Architecture overview](docs/architecture/overview.md).

## Documentation

- [Installation](docs/getting-started/install.md) (Linux, Windows, published image, TLS, without Docker)
- [User guide](docs/user-guide/using-targethub.md) · [Administration](docs/admin-guide/administration.md)
- [Agents: Linux, Raspberry Pi, Windows](docs/agents/agent-guide.md) · [DD power](docs/power/dd-power.md)
- [CLI, SDK and CI / hardware-in-the-loop](docs/automation/ci-hil.md) · [VS Code](vscode-extension/README.md)
- [Upgrade and rollback](docs/operations/upgrade.md) · [Backup](docs/deployment/backup.md) ·
  [TLS](docs/deployment/tls.md) · [Troubleshooting](docs/operations/troubleshooting.md) ·
  [Security](docs/operations/security.md)
- [Development](docs/developer-guide/local-docker-development.md) ·
  [Simulators and demo lab](docs/development/simulators.md) ·
  [Manual verification checklist](docs/MANUAL_VERIFICATION_CHECKLIST.md)

Browse them as a site with `pip install mkdocs-material && mkdocs serve`.

## Repository layout

```text
backend/            FastAPI server, Alembic migrations, tests; agent files in backend/app/web/agent/
frontend/           React UI (built into the server image)
sdk/python/         Python SDK and `targethub` CLI
vscode-extension/   VS Code extension
tools/              Mock DD server, virtual board, demo lab
scripts/            install, backup/restore, admin reset, end-to-end tests
docs/               Documentation (MkDocs)
```

## Project status

0.2.0 is feature-complete for reservations, sessions, serial, power (DD/HTTP/GPIO) and deploy, and is
covered by automated tests on Linux. The DD driver, agents on Raspberry Pi and Windows hosts, and real
boards have been verified **only against simulators** so far; please run the
[manual verification checklist](docs/MANUAL_VERIFICATION_CHECKLIST.md) on your lab and report differences.
SSH/Telnet proxying and J-Link debugging are on the [roadmap](docs/development/ROADMAP.md).

## Contributing

Issues and pull requests are welcome. Run the test suites described in
[development docs](docs/developer-guide/local-docker-development.md) before opening a PR; CI runs them
on every push.
