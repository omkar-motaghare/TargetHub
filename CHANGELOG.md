# Changelog

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
