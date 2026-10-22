# TargetHub Agent Operations

## Phase 7 operation protocol (Agent polls for work)

TargetHub Phase 7 uses a **server-queued, Agent-polled operation protocol** for serial access.
The Agent does not expose an inbound control port; it authenticates to TargetHub and polls for work.

Why this approach:

- works when Agents are behind NAT/firewalls;
- keeps authorization enforcement on the server/session boundary;
- constrains execution to a strict allowlist;
- avoids arbitrary command execution surfaces.

### Protocol endpoints

All endpoints are under `/api/v1/agents/{agent_id}` and require `Authorization: Bearer <agent-credential>`.

1. `POST /operations/poll`
   - Agent requests the next operation for itself.
   - TargetHub returns either no work, or one leased operation owned by that Agent.
2. `POST /operations/{operation_id}/complete`
   - Agent reports success/failure and structured result data.

### Runtime/security guarantees

- Operations require an active, unexpired, owned TargetHub session.
- Session capability must be `serial`.
- Session `agent_id` and `resource_id` must match the configured capability binding.
- Agent authentication is mandatory for poll/complete.
- Operation allowlist is explicit: `open`, `read`, `write`, `close`.
- No remote shell operation is available in this protocol.
- Serial device access happens only on the Agent host.
- If Agent connectivity is lost, TargetHub returns clear timeout/offline conflicts.

### Simulated serial mode

Simulated serial remains available for development by publishing simulated serial resources
from the Agent configuration (for example `sim://...` and/or `metadata.simulated=true`).
The same authenticated protocol is used; only the local transport implementation differs.

## What is implemented

TargetHub provides the first-version Agent enrollment lifecycle:

1. Team Admin creates an Agent enrollment from the Web UI.
2. TargetHub creates a 30-minute, single-use enrollment token.
3. The UI displays a copyable installation command.
4. The installer downloads the dependency-free Agent runtime and creates a systemd instance.
5. The Agent exchanges the enrollment token for a long-lived Agent credential.
6. The token is removed from the Agent configuration after successful enrollment.
7. The Agent sends authenticated heartbeats every 15 seconds by default.
8. TargetHub stores the latest discovered resources.
9. Team Admin can see Agent status and resources in the Web UI.
10. Team Admin can disable/enable an Agent or revoke its credential.
11. Agents with no heartbeat for more than 45 seconds are shown as offline.
12. Multiple independent Agents can run on the same Linux host.
13. A disabled or credential-revoked Agent can be re-enrolled using the same Agent name; an active Agent name cannot be reused.

## Platform requirement

The Agent is intended for **Linux-based machines**. TargetHub does not require the administrator to declare whether the host is a Raspberry Pi, PC, server, VM, or another Linux system.

The installer checks that it is running on Linux. The Agent runtime performs the same check before starting.

## Agent enrollment

Open the **Agents** administration section, enter a unique Agent name, and choose **Create enrollment**. There is no deployment-scenario selection.

Run the generated command on the Linux machine that should host that Agent:

```bash
curl -fsSL http://<targethub>/web/agent/install.sh | sudo bash -s -- \
  --targethub-url 'http://<targethub>' \
  --enrollment-token '<one-time-token>'
```

The same command shape works whether the Linux host is:

- the machine running TargetHub;
- a remote Linux server;
- a Raspberry Pi;
- a Linux VM; or
- another supported Linux-based embedded computer.

The administrator does not need to tell TargetHub which hardware class was selected. The Agent reports its hostname and discovered resources after enrollment.

## Multiple Agents on one Linux machine

Multiple enrollments can be installed on the same physical Linux host. Each enrollment receives a unique instance identifier derived from its one-time token and gets its own configuration and systemd service:

```text
/etc/targethub-agent/<instance>.json
targethub-agent@<instance>.service
```

For example:

```bash
systemctl list-units 'targethub-agent@*'
```

Each Agent has an independent credential and resource inventory.

## Agent installation

The installer:

- requires root privileges;
- requires a Linux-based host;
- requires Python 3, curl, and `sha256sum`;
- validates the downloaded runtime (`python3 -m py_compile`) before replacing the installed file;
- installs the Agent under `/opt/targethub-agent`;
- stores per-enrollment configuration under `/etc/targethub-agent/` with mode `0600`;
- keeps `/etc/targethub-agent/` restricted to root (`0700`);
- creates the templated `targethub-agent@.service`;
- enables and starts the specific enrollment instance;
- cleans temporary installer artifacts on failure and removes newly-created config for failed first-time installs.

Check an instance with:

```bash
systemctl status targethub-agent@<instance>
journalctl -u targethub-agent@<instance> -f
```

## Resource discovery

The first runtime discovers:

- `/dev/ttyUSB*` serial resources;
- `/dev/ttyACM*` serial resources;
- `/dev/serial/by-id/*` stable serial resources;
- non-loopback Linux network interfaces;
- optional custom resources defined in the Agent configuration.

Hardware-specific discovery can be extended without changing the enrollment protocol.

Resource identity handling notes:

- The runtime prefers stable `/dev/serial/by-id/*` entries over transient `/dev/ttyUSB*` and `/dev/ttyACM*`.
- Duplicate serial aliases for the same physical device are de-duplicated before heartbeat.
- On heartbeat updates, TargetHub preserves an existing resource record when `resource_key` + `resource_type` is unchanged, so resource IDs remain stable across routine heartbeats.

## Credential lifecycle

Enrollment token:

- expires after 30 minutes;
- can be consumed once;
- is stored only as a keyed hash in TargetHub.

Agent credential:

- is issued only after successful enrollment;
- is stored only as a keyed hash in TargetHub;
- authenticates heartbeat/operation calls with `Authorization: Bearer <agent-credential>`;
- is independently revocable;
- becomes unusable when the Agent is disabled.

Runtime retry behavior:

- Enrollment retries with bounded exponential backoff for transient transport failures.
- Expired/used/invalid enrollment tokens are treated as permanent failures and require a new enrollment.
- Heartbeat retries with bounded exponential backoff and resumes the normal interval after a successful heartbeat.

## Manual Linux validation (real serial device)

Use this test only on a Linux host with a real serial adapter connected (for example `/dev/ttyUSB0`).

1. Enroll and start Agent:
   - create enrollment in TargetHub UI;
   - run installer command on the Agent host;
   - confirm `targethub-agent@<instance>.service` is active.
2. Verify Agent reports serial resource:
   - in UI or `GET /api/v1/agents`, confirm the Agent resource list includes the target serial device.
3. Map capability:
   - create/update a target capability with `capability_type=serial`;
   - set matching `agent_id` and `resource_id` from the Agent resource list.
4. Reserve + session:
   - create an active reservation;
   - create a session for `serial`.
5. Exercise operations:
   - `POST /api/v1/sessions/{session_id}/serial/open`
   - `POST /api/v1/sessions/{session_id}/serial/write` with `{"text":"help\\r\\n"}`
   - `GET /api/v1/sessions/{session_id}/serial/read`
   - `POST /api/v1/sessions/{session_id}/serial/close`
6. Negative checks:
   - disable/revoke Agent and confirm serial operations fail with a clear conflict/authentication error;
   - close/expire session and confirm operations are rejected.

## Operational recovery

If an Agent credential is revoked or the Agent is disabled, create a new enrollment using the **same Agent name** to restore that Agent identity with a new credential. The existing active credential is never replaced merely by creating an enrollment; active Agent names remain protected from accidental credential replacement.

If an enrollment token expires or is consumed, create another enrollment rather than reusing the old token.
