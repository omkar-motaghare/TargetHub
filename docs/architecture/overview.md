# Architecture overview

```text
 Browser UI (React) · VS Code extension · targethub CLI / Python SDK · CI jobs
                       │ HTTPS: REST /api/v1, WebSocket /api/v1/sessions/{id}/serial/ws
 ┌─────────────────────┴───────────────────────────────────────────────────────────┐
 │ TargetHub server (FastAPI, Gunicorn/Uvicorn workers)                             │
 │  auth & roles · targets & capabilities · reservations · waitlist · policy        │
 │  sessions · provider gateway · agent operation queue · notifications/webhooks   │
 │  audit · metrics · scheduler (expiry, warnings, waitlist, liveness, retention)  │
 └──────┬──────────────────────────────┬───────────────────────────────┬───────────┘
        │ SQL                           │ HTTP (server-hosted providers) │ long-poll (agents connect out)
   PostgreSQL / SQLite        DD power system · HTTP PDUs        TargetHub agents (Linux / Pi / Windows)
                                                                     │ serial · GPIO · deploy commands
                                                                 Embedded targets
```

## Core model

| Concept | Meaning |
| --- | --- |
| **Target** | A board: name, lab, tags, status (available/maintenance/retired) |
| **Capability** | Something you can do with a target: `serial`, `power`, `reset`, `deploy` (plus bridge types). Backed by an agent resource or a server-hosted provider (`dd`, `http`). |
| **Reservation** | Exclusive ownership of a target for a time window. Overlaps are prevented under a per-target lock. |
| **Waitlist entry** | A queued request for a target or any target with a tag; fulfilled automatically on release/expiry |
| **Session** | One capability of an owned reservation; all hardware operations go through a session |
| **Agent / resource** | An enrolled host and the hardware it reports (serial ports, configured relays and deploy targets) |
| **Agent operation** | A queued operation for an agent, leased atomically, with timeout and result |

## Request flow: power cycle via DD (no agent)

1. User opens a *power* session on their reservation → server checks ownership, window and binding.
2. `POST /sessions/{id}/execute {"operation": "cycle"}` → provider gateway builds the DD provider from
   `provider_config` and the API key from the server environment.
3. DD driver: OFF → poll status until confirmed → wait → ON → poll until confirmed. Result includes
   `confirmed`. Audit row and metrics recorded.

## Request flow: serial console via agent

1. The browser opens the WebSocket and authenticates with its access token in the first frame.
2. The server queues `open` for the agent that owns the bound resource; the agent's long-poll returns it
   immediately; the agent opens the port and starts a background reader (1 MiB buffer).
3. The socket's reader task queues `read` operations with `wait_ms` (long reads), forwards output to the
   browser and the transcript; keystrokes become `write` operations.
4. When the session ends, the server queues a cleanup `close`; the agent releases the port.

## Concurrency and reliability

- Operation claims and enrollment-token claims are conditional `UPDATE`s, so they are safe with several
  workers and on PostgreSQL or SQLite (WAL mode, busy timeout).
- Waiters are woken by in-process signals with a 250 ms database fallback, so multi-worker deployments stay correct.
- Agents run operations concurrently (default 8) but serialise power/deploy per resource.
- The scheduler runs in every worker; each step is idempotent and claims its rows.

## Security boundaries

See [Security](../operations/security.md). Hardware-affecting configuration (device paths, GPIO lines,
flash commands) lives on agents; power-system secrets live in the server environment; the API redacts
provider internals for non-admins.

## Technology

Python 3.12, FastAPI, SQLAlchemy 2, Alembic, Pydantic 2, loguru · React 18, react-router 7, Vite 7,
xterm.js · PostgreSQL 15+ (SQLite for small/dev installs) · Docker Compose, optional Caddy for TLS.
Historical design notes are in [project journal](../project-journal/PROJECT_COMPLETION_PLAYBOOK.md).
