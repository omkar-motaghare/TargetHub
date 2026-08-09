# TargetHub Agent Enrollment Architecture

## Purpose

This document records the planned operator-friendly Agent enrollment flow and maps it onto the Agent implementation that already exists in TargetHub. The goal is that a Team Admin can add an Agent from the TargetHub Web UI without manually creating database records or guessing internal Agent IDs.

## Existing implementation

The current backend already has the core Agent lifecycle pieces:

- `Agent` stores the Agent identity (`id`, `name`), hostname, online/offline status, enabled state, and last-seen timestamp.
- `AgentResource` stores resources discovered by an Agent and is linked to the Agent with a cascading relationship.
- `GET /api/v1/agents` lists Agents.
- `POST /api/v1/agents/register` creates or reactivates an Agent using its name and hostname.
- `POST /api/v1/agents/{agent_id}/heartbeat` updates liveness and replaces the Agent's reported resources.
- `GET /api/v1/agents/{agent_id}` returns an Agent and its resources.

The current registration endpoint is intentionally simple, but it is not yet a secure enrollment mechanism: registration is based on a caller-supplied name and hostname and does not establish a secret credential owned by the Agent.

## Target enrollment flow

The Web UI should expose an **Agents** administration area. A Team Admin selects **Add Agent** and creates an enrollment record. TargetHub generates a short-lived, single-use enrollment token and presents an installation command/configuration to the administrator.

The administrator then installs the lightweight Agent runtime on the desired machine and supplies the TargetHub URL plus the enrollment token. The Agent connects outbound to TargetHub and exchanges the enrollment token for a long-lived Agent credential. From that point onward, the Agent authenticates using its own credential rather than the enrollment token.

The normal lifecycle is:

1. Team Admin opens **Agents → Add Agent**.
2. Admin gives the Agent a human-readable name and selects the intended deployment scenario.
3. TargetHub creates a pending enrollment and a one-time, expiring enrollment token.
4. UI shows copyable installation/configuration instructions.
5. Agent starts and calls the enrollment endpoint with the token and its local identity/hostname.
6. TargetHub validates the token, binds the Agent identity to the pending enrollment, consumes the token, and returns the Agent credential/configuration.
7. Agent stores the credential locally and starts its heartbeat loop.
8. TargetHub marks the Agent online and updates discovered resources from heartbeat reports.
9. The Web UI shows installation/enrollment state and subsequently live Agent status/resources.

### Security properties

- Enrollment tokens are short-lived and single-use.
- The raw enrollment token should not be stored in plaintext after issuance; store a secure hash and compare against the presented token.
- Agent credentials are distinct from enrollment tokens and can be revoked independently.
- Disabled/revoked Agents must be rejected by authenticated heartbeat/API calls.
- Heartbeat should not accept an arbitrary Agent ID as sufficient authentication.
- The Agent should make outbound connections to TargetHub; TargetHub should not require inbound connectivity to the Agent for normal operation.

## Deployment scenarios

### Scenario 1 — TargetHub and Agent on the same Linux machine

The team runs the main TargetHub application and the Agent runtime on one Linux host.

**Configuration:**

- TargetHub URL points to the local TargetHub service/container.
- The Agent receives its one-time enrollment token from the Web UI.
- Agent and TargetHub communicate over the local Docker/network interface or localhost as appropriate.
- No hardware-network routing is required for the Agent itself.

This is the simplest installation and should be the default quick-start path.

### Scenario 2 — TargetHub on Linux, Agent on a remote Raspberry Pi

The main TargetHub application runs on a Linux server while hardware is physically/network-wise closer to a Raspberry Pi.

**Configuration:**

- Team Admin creates the Agent in the TargetHub Web UI.
- The generated instructions contain the TargetHub base URL and one-time enrollment token.
- The Raspberry Pi runs only the Agent runtime.
- The Pi initiates an outbound connection to TargetHub.
- Heartbeats report the Pi hostname and discovered hardware/resources.

The TargetHub server therefore does not need to reach into the remote lab network merely to keep an Agent connected.

### Scenario 3 — TargetHub and Agent on one Raspberry Pi

The team has no separate Linux server and uses a Raspberry Pi as the complete local TargetHub installation and Agent host.

**Configuration:**

- TargetHub and the Agent run on the same Raspberry Pi.
- The Team Admin accesses the Web UI from another workstation on the LAN.
- The Admin creates/enrolls the local Agent using the same UI flow.
- The Agent connects to the local TargetHub URL.
- The same enrollment/security model is used; only the physical deployment differs.

This keeps the operator experience consistent across all three deployment models.

## Mapping to the current code

| Enrollment concept | Existing TargetHub component | Required evolution |
|---|---|---|
| Agent identity | `backend/app/models/agent.py` → `Agent` | Keep; add enrollment/credential state as the secure flow is implemented |
| Hardware/resource inventory | `AgentResource` | Keep; continue replacing reported resources on heartbeat |
| Agent registration | `backend/app/api/v1/agents.py` → `/agents/register` | Evolve into token-authenticated enrollment; retain a clear compatibility/migration strategy |
| Heartbeat | `/agents/{agent_id}/heartbeat` | Require Agent credential authentication and update resources |
| Agent business logic | `backend/app/services/agent_service.py` | Add enrollment/token lifecycle and authenticated heartbeat logic |
| Persistence | `backend/app/repositories/agent_repository.py` | Add enrollment lookup, token/credential persistence, and revocation operations |
| Web UI | Not yet implemented in the repository (`frontend/` is currently a placeholder) | Build Agents list, Add Agent, enrollment instructions, status, revoke/disable controls |
| Deployment/install | Existing Docker/backend structure | Add a standalone Agent package/service and scenario-specific installation instructions |
| Documentation | `docs/architecture/` | This document becomes the architecture reference for future implementation |

## Recommended implementation sequence

1. Introduce enrollment persistence and secure token hashing.
2. Add a dedicated enrollment endpoint and one-time token validation.
3. Add Agent credential issuance and authenticated heartbeat.
4. Add Agent disable/revoke behavior.
5. Add the standalone Agent runtime and configuration mechanism.
6. Add Web UI support for Add Agent and copyable installation instructions.
7. Add scenario-specific installation guides for Linux/LAN and Raspberry Pi.
8. Add integration tests covering token expiry, token reuse, credential authentication, disabled Agents, heartbeat, and resource reporting.

## Important design decision

The Team Admin should configure an Agent from the TargetHub Web UI, but the Web UI should **not** ask the administrator to manually enter hardware resources. Hardware/resource discovery belongs to the Agent. The admin configures the Agent's identity and deployment; the Agent discovers and reports what is actually available.

Likewise, the three deployment scenarios should share one enrollment protocol. The difference is only where the TargetHub server and Agent runtime are physically deployed.
