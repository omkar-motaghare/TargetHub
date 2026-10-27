# Agent protocol reference

How the server and agents talk. Useful when debugging, writing an alternative agent, or reviewing security.
For installation and configuration see the [agent guide](agent-guide.md).

## Transport

- The agent makes all connections (HTTPS to the server URL). The server never connects to an agent.
- Authentication: `Authorization: Bearer <agent credential>`. The credential is issued once at enrollment
  and the server stores only an HMAC of it.

## Endpoints

| Method and path | Purpose |
| --- | --- |
| `POST /api/v1/agents/enroll` | Exchange a one-time enrollment token for `agent_id` + credential |
| `POST /api/v1/agents/{id}/heartbeat` | Every `heartbeat_interval` s: hostname, agent version, platform, resource inventory |
| `POST /api/v1/agents/{id}/operations/poll` | Long-poll (up to `wait_seconds`) for the next operation; leases it to this agent |
| `POST /api/v1/agents/{id}/operations/{op}/complete` | Report `success`, `message`, `data` |

An agent is **online** while heartbeats arrive (offline after 45 s without one, configurable with
`TARGETHUB_AGENT_OFFLINE_AFTER_SECONDS`).

## Operations

A session operation becomes an `agent_operations` row bound to the session, agent and resource. Claims are
atomic, so an operation runs exactly once even with several server workers. Results wake the waiting API
request immediately.

| Resource type | Operations | Notes |
| --- | --- | --- |
| serial | `open`, `read` (`size`, `wait_ms` ≤ 5000), `write` (`text`), `close` | Reader thread buffers up to 1 MiB per port; a new session takes over a port from an ended one |
| power | `status`, `on`, `off`, `cycle`, `reset` | GPIO or DD; per-resource lock |
| deploy | `deploy` (`url`, `sha256`), `status` | Download, verify, run local command; may run detached (`wait=false` → HTTP 202) |

Validation happens twice: the server checks session ownership, expiry, capability binding and operation
allowlist; the agent checks the resource is in its local configuration or discovery and that the serial
path is allowed. Operations whose lease expires are timed out and reported as failed.

When a session ends, the server queues a `close` with `params.cleanup = true` so the port is released
even though the session is no longer active.

## Asynchronous operations (API clients)

`POST /api/v1/sessions/{id}/execute?wait=false` returns `202 {"operation_id": …}`.
Poll `GET /api/v1/sessions/{id}/operations/{operation_id}` until `status` is `completed`, `failed` or
`timed_out`. The SDK's `submit()` / `wait_operation()` and the web UI's deploy panel do this.

## Serial WebSocket

`/api/v1/sessions/{id}/serial/ws`. The first frame must be `{"type": "auth", "token": "<access or API token>"}`.
Then:

- server → client: `ready`, `output` (`data`), `notice`, `closed`, `pong`;
- client → server: `input` (`data`), `ping`.

Input and output are recorded in the session transcript (`GET /api/v1/sessions/{id}/serial/log`).

## Simulated resources

Resources with keys `sim://…` (or `metadata.simulated = true`) are served by the agent's built-in
virtual board. They use the same protocol and are meant for demos and tests.
