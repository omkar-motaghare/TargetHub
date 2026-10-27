# Administration

Everything here is under **Admin** in the web UI and needs the *admin* role. All changes are recorded in
the **Activity log** (audit), filterable by user, action and target.

## Overview

**Admin → Overview** shows live counts (targets, reservations, sessions, waitlist, agents) and a
**configuration check** that lists what will stop users from working, e.g. a capability whose agent is offline
or disabled, a missing agent resource, a power capability without a driver, a simulated capability on a
production server, or a secret environment variable (`api_key_env`, `bearer_token_env`, …) that is not set
on the server. The same problems appear on each affected target in **Admin → Targets**. Start here after
installing, upgrading or changing `.env`.

## Users and roles

**Admin → Users** creates accounts (username, display name, e-mail, role, temporary password).

| Role | Typical use |
| --- | --- |
| admin | Lab owners. Manage everything, force-release reservations. Keep this group small. |
| user | Engineers who reserve and use boards. |
| viewer | Managers, other teams, dashboards: read-only availability and calendar. |

- **Disable** a user instead of deleting them when someone leaves. They are signed out immediately
  (access and refresh tokens and API tokens stop working) and their history stays intact.
- **Reset password** sets a new temporary password and signs the user out everywhere.
- Login, password change and bootstrap are rate limited per IP (`AUTH_MAX_FAILURES`,
  `AUTH_FAILURE_WINDOW_SECONDS`).

### Recovering access

If no admin can sign in, use the server console (no web access needed):

```bash
scripts/reset_admin_user.sh                 # list users
scripts/reset_admin_user.sh reset alice     # prints a new random password for alice
scripts/reset_admin_user.sh create rescue   # new admin with a random password
scripts/reset_admin_user.sh enable alice    # re-enable a disabled account
```

On Windows or without the script: `docker compose exec api python -m app.manage --help`
(`list-users`, `reset-password`, `create-admin`, `enable-user`, `make-admin`; add `--password-stdin`
to set a password you choose). These actions are audited as `manage.*`.

## Targets

**Admin → Targets** manages the inventory.

- **Name**, **lab**, description, **tags** (lowercase words such as `stm32`, `rack-2`, `nightly`; users filter
  and *reserve any* by tag).
- **Status**: *available*, *maintenance* (with a reason shown to users, no new reservations) or *retired*.
  Changing the status notifies webhooks (`target.status`).
- **Force release** ends someone's reservation (they are notified, the waitlist advances). Use it for
  abandoned boards.

### Capabilities

A target has one or more capabilities. Each is backed by one of these:

| Backend | Where it runs | Use for |
| --- | --- | --- |
| **Agent hardware** | On an agent host | Serial consoles (USB-serial, COM ports), GPIO relays, deploy/flash commands. Pick the agent and one of the resources it reported. |
| **DD power system (server)** | On the TargetHub server | DD relay endpoints. No agent needed. See [DD power](../power/dd-power.md). |
| **HTTP power controller (server)** | On the TargetHub server | Any PDU/relay with the simple REST contract below. |
| **HTTP bridge (server, JSON config)** | On the TargetHub server | Deploy, debugger and network bridges that implement TargetHub's REST contract. |
| **Simulated (demo only)** | Server | Demos and training. Refused unless `ALLOW_SIMULATED_PROVIDERS=true`. |

Agent-backed capabilities only reference a resource. The actual device path, GPIO line or flashing
command lives in the agent's local configuration, so a compromised server cannot make an agent open
arbitrary devices or run arbitrary commands.

#### HTTP power controller contract

```text
GET  {controller_url}/v1/outlets/{outlet_id}/status   -> {"power": "on"|"off"} or {"is_on": true}
POST {controller_url}/v1/outlets/{outlet_id}/on|off|reset|cycle
```

```json
{"driver": "http", "controller_url": "https://pdu.lab.local", "outlet_id": "7",
 "auth_type": "bearer", "bearer_token_env": "TARGETHUB_PDU_TOKEN",
 "timeout_seconds": 3, "cycle_delay_seconds": 2, "supports_cycle_command": false}
```

`auth_type` is `none`, `bearer` (`bearer_token_env`) or `basic` (`basic_username_env`,
`basic_password_env`). **Test connection** in the editor reads the outlet status from the server without
switching anything. As with DD, these name **environment variables** on the server, so secrets never
enter the database. Add them to `.env` and run `docker compose up -d`.

## Agents

**Admin → Agents** shows each agent's status (online when it sent a heartbeat in the last 45 s), host,
platform, agent version and discovered resources.

- **Create enrollment** issues a single-use token valid for 30 minutes and shows install commands for
  **Linux / Raspberry Pi** and **Windows**. Run the command on the host. Details: [agent guide](../agents/agent-guide.md).
- **Disable** stops an agent from receiving work; **Revoke credential** forces re-enrollment (use it if a
  host is lost or compromised). A disabled or revoked agent name can be re-enrolled.
- Offline and back-online transitions are announced to webhooks (`agent.offline`, `agent.online`).

## Reservation policy

**Admin → Settings → Reservation policy** (users can read it; only admins change it):

| Setting | Default | Meaning |
| --- | --- | --- |
| Max duration | 480 min | Longest single reservation, including extensions |
| Default duration | 60 min | Preselected in the reserve dialog |
| Max advance booking | 30 days | How far ahead a reservation may start |
| Max active reservations per user | 0 (no limit) | Concurrent reservations one user may hold |
| Expiry warning | 10 min | "Ending soon" notification before the end (0 = off) |
| Allow extend when waitlisted | off | If off, nobody can extend while others are waiting |
| Waitlist entry lifetime | 24 h | Unfulfilled entries expire |
| Transcript retention | 30 days | Serial transcripts are deleted afterwards |
| Audit retention | 365 days | Audit entries are deleted afterwards |

Admins are exempt from the duration, advance-booking and per-user limits, and can extend while others wait.

## Notifications and webhooks

**Admin → Settings → Webhooks** sends events to chat or automation. Formats:

- **Slack**: incoming-webhook URL.
- **Microsoft Teams**: incoming-webhook / workflow URL (MessageCard).
- **Generic**: JSON `{"event", "message", "data", "timestamp", "instance"}`. With a secret, each request carries
  `X-TargetHub-Signature: sha256=<HMAC-SHA256 of the body>` and `X-TargetHub-Event`.

Events: `reservation.created`, `reservation.released`, `reservation.expiring`, `reservation.expired`,
`reservation.extended`, `waitlist.fulfilled`, `target.status`, `agent.offline`, `agent.online`.
**Send test** posts a sample event. Deliveries are retried 3 times and never block users. Secrets are
write-only in the UI.

## Monitoring

- `GET /health/live` (process up) and `GET /health/ready` (database reachable) for load balancers.
- `GET /metrics` (Prometheus) needs `Authorization: Bearer $METRICS_TOKEN` (from `.env`) or an admin token.
  It includes request counts/latency, provider operation counts and gauges for active reservations,
  sessions, online agents and waitlist length.
- Logs: `docker compose logs api`; set `TARGETHUB_LOG_FORMAT=json` for log shippers. Every response carries
  an `X-Request-ID` that also appears in the log lines.

## Backups

See [Backup and restore](../deployment/backup.md). Back up before every upgrade.
