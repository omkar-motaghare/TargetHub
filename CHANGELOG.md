# Changelog

## v0.2.0 — 2026-10-27

Server, agents and web UI ready for team deployment. DD power, Raspberry Pi/Windows agents and real
boards have been verified with simulators only; see docs/MANUAL_VERIFICATION_CHECKLIST.md.

### Upgrade notes
- The PostgreSQL volume changed from `targethub_postgres_data` to `<project>_pgdata`: copy it before the
  first start (docs/operations/upgrade.md). Redis and MinIO are no longer used.
- Everyone signs in again once (refresh-token sessions). CI should use personal API tokens.
- Simulated providers are disabled outside development; capabilities without a real backend are refused.
  Demo servers: `ALLOW_SIMULATED_PROVIDERS=true`.
- `/metrics` requires `METRICS_TOKEN` or an admin token. The legacy dashboard is removed.
- Upgrade agents to 0.2.0.

### Lab features
- Live availability for all users, tags, maintenance/retired status with a reason, lab calendar.
- Reservation policy (max duration, advance booking, per-user limit, warnings, retention), extend,
  reserve-any-by-tag, waitlist with automatic assignment, admin force release.
- In-app notifications and Slack / Teams / HMAC-signed generic webhooks (reservation, waitlist, target and
  agent events; `agent.offline` is sent once, `agent.online` on return).
- Background scheduler: expiry, ending-soon warnings, waitlist, agent liveness, retention, gauges.

### Sessions, serial and power
- WebSocket serial console (xterm.js) with buffered agent reads, reconnect and downloadable transcripts.
- Asynchronous operations (`wait=false`, 202 + polling) for long deploys.
- DD Endpoint Control API driver on the server, with confirmation polling and power-cycle reset; HTTP power controllers;
  secrets referenced by environment variable only.

### Accounts and security
- Roles admin / user / viewer; disable users; 15-minute access tokens with rotating refresh tokens and reuse
  detection; sign out everywhere; personal API tokens; PBKDF2 600k with transparent rehash.
- `python -m app.manage` / `scripts/reset_admin_user.sh` for console recovery.

### Agents
- Agent 0.2.0 for Linux, Raspberry Pi and Windows (pyserial, Scheduled Task installer with checksum
  verification and ACL-protected config); concurrent operations with per-resource locks; serial background
  reader, session takeover, idle reaper and path allowlist; DD fallback; built-in `sim://` board.

### Web UI
- Admin overview with a configuration check (offline/disabled agents, missing resources, unset secret
  variables, simulated capabilities) shown on the overview and on each affected target; `GET /api/v1/system/overview`.
- **Test connection** for DD and HTTP power capabilities (`POST /api/v1/system/power-check`, read-only).
- Admin sections have their own URLs (`/app/admin/<section>`); HTTP power basic auth; clearer error texts.
- Redesigned targets page, reservations, sessions and session workspace, calendar, account page,
  notification bell; admin targets (capability editor for agent/DD/HTTP backends), users, agents
  (Linux/Windows install commands), settings (policy, webhooks), overview and activity log.

### Operations
- `scripts/install.ps1` for Windows servers; `install.sh --image`; fixed an `install.sh` abort when `.env`
  lacked a key.
- CI: lint, backend on SQLite and PostgreSQL migrations, live agent E2E, frontend, Playwright, Windows agent
  tests, Docker build-and-boot. Release workflow publishes a multi-arch image (amd64/arm64) and release assets.
- Simulators: DD mock server, pty virtual board, demo lab and its verifier.
- Documentation rewritten: install, user, admin, agents, DD power, upgrade, troubleshooting, security, architecture.

### Clients (preview, verification deferred)
- Python SDK/CLI and VS Code extension updated for API tokens, waitlist, extend and the long-poll console.

## Unreleased (pre-0.2.0)

### Security
- Login, password change and admin bootstrap are rate limited after repeated failures (`AUTH_MAX_FAILURES`, `AUTH_FAILURE_WINDOW_SECONDS`); responses are 429 with `Retry-After`.
- Agent enrollment tokens are claimed atomically, so concurrent requests cannot both mint a credential.

### Agent
- Installer works on BusyBox/Yocto images without `curl`, `useradd`, `getent` or `usermod` (falls back to `wget`/Python and `adduser`/`addgroup`).
- Agent verifies its config is writable before spending a single-use enrollment token.
- Verified on a Raspberry Pi 5 (Yocto, read-only NFS root): enrollment, discovery, pty serial, fake-GPIO power, restart and offline detection, hardened systemd unit. Real GPIO, a real serial target and a persistent install (needs the Yocto image) remain untested.

## v0.1.0 — 2026-10-22

First tagged release (local tag; not published).

### Security
- Hub refuses to start with an empty, placeholder or short `SECRET_KEY` outside development/test; compose files require it.
- Non-admin API responses no longer expose `provider_key`, `provider_config`, `agent_id` or `resource_id` (targets, capabilities, sessions, operation results).
- Reservation overlap check runs under a per-target lock (verified on SQLite and PostgreSQL 16).
- Agent installer verifies sha256 of installer and agent, requires `https://` unless `--allow-insecure-http`, runs the agent as a dedicated `targethub` user under a hardened systemd unit.

### Agent (Raspberry Pi / Linux, stdlib-only Python)
- GPIO power on/off/status/cycle/reset (sysfs and gpiod backends, active-low, pulse), checksummed deploy, USB/serial discovery, TLS CA bundle option, graceful SIGTERM, jittered backoff, sd_notify watchdog.
- Hub routes power and deploy sessions through agent operations (opt-in `transport=agent`) with per-family allowlists, timeouts and stale-operation reaping.

### Hub, UI and ops
- React UI: reservations, targets, session workspace with serial terminal, power and deploy panels, admin (agents/enrollment with checksum-verified install command, users, audit, targets).
- Request-id correlated logs, JSON log mode, audit action filter, `/metrics`, `/health/live`, `/health/ready`.
- `scripts/backup.sh` / `scripts/restore.sh` (checksummed), Caddy TLS compose overlay, loopback-only datastore ports.

### Clients
- Python SDK (`targethub_sdk`) and `targethub` CLI.
- VS Code extension: target tree, reserve/release, power commands, serial output channel.

### Testing
- Backend pytest suite, live hub + real agent E2E (`scripts/e2e-agent.sh`), Playwright browser smoke (`scripts/e2e-ui.sh`), frontend vitest, SDK/CLI tests, extension compile and vitest. CI workflow covers each.

### Known limitations
- No real Raspberry Pi, GPIO, relay or USB hardware has been tested; the gpiod path and deploy flashers are exercised only with fakes. See `docs/agents/raspberry-pi.md`.
- CI workflow has not been run on GitHub; validation was run locally.
- Frontend runtime dependency `react-router` has 2 moderate advisories whose fix is a major upgrade (v7); dev-only tooling (vitest/tinypool, esbuild) has advisories too. Not exploitable in the shipped bundle but should be upgraded.
- Sessions still expose `agent_id`/`resource_id` to the session owner.
- No Postgres exclusion constraint for reservations; locking relies on application-level row locks.
- Upgrade migration on a representative pre-existing production database has not been tested.
