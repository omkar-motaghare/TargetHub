# Phase 7 Agent-Backed Serial Vertical Slice Record

**Project:** TargetHub  
**Repository:** `/home/omkar_motaghare/TargetHub`  
**Date:** 2026-09-28  
**Milestone:** Phase 7 - first real Agent-backed hardware vertical slice (serial)

## Protocol decision

Phase 7 uses a **server-queued, Agent-polled operation protocol**.

Chosen approach:

- Agent calls `POST /api/v1/agents/{agent_id}/operations/poll` with Agent credential.
- Server returns one leased operation for that Agent or no work.
- Agent executes only local serial transport operations.
- Agent reports result through `POST /api/v1/agents/{agent_id}/operations/{operation_id}/complete`.

This keeps serial device access on the Agent host, avoids inbound Agent ports, and works behind NAT/firewalls.

## Implemented boundary and controls

- Operation execution requires an active, unexpired, owned session.
- Session capability must be `serial`.
- Session `agent_id` and `resource_id` must match current capability binding.
- Agent authentication is required on poll/complete endpoints.
- Operation allowlist is explicit and narrow: `open`, `read`, `write`, `close`.
- Arbitrary shell execution is not available through this path.
- Real serial I/O is performed only by the Agent runtime on its local host.
- Releasing a reservation closes all active sessions tied to that reservation.
- Offline/disconnected behavior returns clear timeout/conflict errors.
- Simulated serial mode remains available for development.
- Real serial tests rely on fake transports and do not require hardware.

## Key implementation points

- Transport orchestration is implemented in `backend/app/services/agent_operation_service.py`.
- Session-gated provider execution and binding revalidation is implemented in `backend/app/services/provider_gateway.py`.
- Reservation release-driven session shutdown is implemented in `backend/app/services/reservation_service.py` via `backend/app/repositories/session_repository.py`.
- Agent-authenticated protocol endpoints are implemented in `backend/app/api/v1/agents.py`.
- Agent runtime poll/complete loop and serial execution are implemented in `backend/app/web/agent/targethub_agent.py`.
- Heartbeat resource model validation is implemented in `backend/app/schemas/agent.py`.

## Tests and validation

### Service and protocol tests

- `tests/test_agent_operation_service.py`
  - allowlist enforcement;
  - timeout/offline error path;
  - cancellation when session expires;
  - cancellation when session is closed;
  - foreign-agent completion rejection.
- `tests/test_auth_rbac.py`
  - poll/complete require Agent credential and matching Agent identity.
- `tests/test_agent_runtime.py`
  - runtime poll and complete protocol with fake HTTP server;
  - simulated serial transport behavior.

### Integration tests

- `tests/test_agent_serial_integration.py`
  - end-to-end serial write/read through queued poll protocol using fake Agent worker;
  - session close blocks further serial operations;
  - reservation release closes the session and blocks further serial operations;
  - disabled Agent and non-owner paths are rejected.

### Validation results (2026-09-28)

```text
python -m pytest -q tests/test_agent_operation_service.py tests/test_agent_runtime.py tests/test_agent_serial_integration.py
13 passed

python -m pytest -q
103 passed
```

## Manual Linux test (real serial device)

A manual real-device Linux validation procedure is documented in:

- `docs/agents/agent-operations.md` under "Manual Linux validation (real serial device)".

That procedure covers enrollment, heartbeat/resource verification, capability mapping, reserve/session flow, serial open/write/read/close operations, and negative checks for disabled/revoked Agent and closed/expired session behavior.

## Exit criteria status

Phase 7 exit criteria are satisfied:

- A user can reserve a target.
- A user can open a session.
- Serial operations execute through an authenticated remote Agent path.
- Session close blocks subsequent access.
- Reservation release closes active sessions and blocks subsequent access.
- Authorization/session constraints prevent unauthorized or stale access.
