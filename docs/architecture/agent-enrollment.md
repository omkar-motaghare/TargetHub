# TargetHub Agent Enrollment Architecture

## Purpose

This document records the operator-friendly Agent enrollment flow and maps it onto the Agent implementation in TargetHub. The goal is that a Team Admin can add an Agent from the TargetHub Web UI without manually creating database records or guessing internal Agent IDs.

## Current implementation status

The first complete enrollment implementation is now present on `develop`.

Implemented components include:

- Agent identity and resource inventory persistence.
- Short-lived, single-use enrollment tokens stored as keyed hashes.
- Agent credential issuance and keyed-hash storage.
- Authenticated heartbeat using `Authorization: Bearer` credentials.
- Agent disable/enable and credential revocation.
- Web UI Agent administration and enrollment instructions.
- Dependency-free Linux/Raspberry Pi Agent runtime.
- One-command installation through the TargetHub-hosted installer.
- Automatic serial/network resource discovery plus custom resource configuration.
- Deployment documentation for all three supported physical layouts.

## Enrollment flow

The Web UI exposes an **Agents** administration area. A Team Admin selects **Create enrollment**, supplies a human-readable Agent name and deployment scenario, and TargetHub generates a short-lived, single-use enrollment token.

The UI presents a copyable installation command. The administrator runs it on the desired Linux or Raspberry Pi host. The Agent connects outbound to TargetHub, exchanges the enrollment token for a long-lived Agent credential, stores the credential locally, removes the enrollment token, and begins its heartbeat loop.

The normal lifecycle is:

1. Team Admin opens **Agents → Create enrollment**.
2. Admin gives the Agent a human-readable name and selects the intended deployment scenario.
3. TargetHub creates a pending enrollment and a one-time, expiring enrollment token.
4. UI shows copyable installation/configuration instructions.
5. Agent starts and calls the enrollment endpoint with the token and local hostname.
6. TargetHub validates the token, binds the Agent identity to the enrollment, consumes the token, and returns the Agent credential.
7. Agent stores the credential locally and starts its heartbeat loop.
8. TargetHub authenticates the heartbeat and updates discovered resources.
9. Web UI shows Agent status and resources.
10. Team Admin can disable/enable the Agent or revoke its credential.

## Security properties

- Enrollment tokens are short-lived and single-use.
- Raw enrollment tokens are not stored in plaintext; TargetHub stores a keyed hash.
- Agent credentials are distinct from enrollment tokens and can be revoked independently.
- Raw Agent credentials are not returned by Agent listing/detail APIs.
- Disabled/revoked Agents are rejected by authenticated heartbeat calls.
- Heartbeat requires a valid Agent credential and verifies that the credential belongs to the URL Agent ID.
- The Agent makes outbound connections to TargetHub; TargetHub does not require inbound connectivity to the Agent for normal heartbeat operation.

## Deployment scenarios

### Scenario 1 — TargetHub and Agent on the same Linux machine

The team runs the main TargetHub application and Agent runtime on one Linux host. The Team Admin creates the enrollment in the Web UI and runs the generated installer command on that host.

The configured `TARGETHUB_PUBLIC_URL` must be reachable by the Agent. For Docker on a Linux host, use the host's LAN address when `localhost` would not resolve to the published TargetHub port from the Agent process.

### Scenario 2 — TargetHub on Linux, Agent on a remote Raspberry Pi

The main TargetHub application runs on a Linux server while hardware is physically/network-wise closer to a Raspberry Pi.

The Team Admin creates an enrollment and selects the remote Raspberry Pi scenario. The Pi runs only the Agent runtime and initiates outbound connections to TargetHub. Heartbeats report the Pi hostname and discovered hardware/resources.

The TargetHub server therefore does not need to reach into the remote lab network merely to keep an Agent connected.

### Scenario 3 — TargetHub and Agent on one Raspberry Pi

The team uses a Raspberry Pi as the complete local TargetHub installation and Agent host.

The Team Admin accesses the Web UI from another workstation on the LAN, creates the enrollment, and runs the generated command on the Pi. TargetHub and Agent use the same enrollment and authentication protocol as the other scenarios.

## Mapping to the implementation

| Enrollment concept | TargetHub component | Status |
|---|---|---|
| Agent identity | `backend/app/models/agent.py` → `Agent` | Implemented |
| Hardware/resource inventory | `AgentResource` | Implemented |
| Enrollment persistence | `AgentEnrollment` | Implemented |
| Enrollment token | `AgentService.create_enrollment()` / `enroll()` | Implemented |
| Agent credential | `Agent.credential_hash` and lifecycle fields | Implemented |
| Agent enrollment API | `backend/app/api/v1/agents.py` → `/agents/enrollments`, `/agents/enroll` | Implemented |
| Authenticated heartbeat | `/agents/{agent_id}/heartbeat` | Implemented |
| Disable/enable/revoke | Agent lifecycle endpoints | Implemented |
| Web UI | `backend/app/web/index.html` and `app.js` | Implemented |
| Agent runtime | `backend/app/web/agent/targethub_agent.py` | Implemented |
| Installation | `backend/app/web/agent/install.sh` | Implemented |
| Deployment documentation | `docs/agents/agent-operations.md` | Implemented |

## Recommended extension points

The enrollment protocol should remain stable as hardware-specific functionality grows. Future Agent work can add richer discovery providers for JTAG/debuggers, power controllers, USB instruments, network-controlled devices, and vendor-specific hardware without changing the enrollment lifecycle.

Likewise, a future authenticated Team Admin identity system should protect the administrative enrollment/disable/revoke endpoints. The current Web UI still represents the project's development-mode local administrator identity and should not be treated as production authentication.

## Important design decision

The Team Admin configures an Agent's identity and deployment from the TargetHub Web UI, but the Web UI does **not** ask the administrator to manually enter hardware resources. Hardware/resource discovery belongs to the Agent. The Agent discovers and reports what is actually available.

The three deployment scenarios share one enrollment protocol. The difference is only where the TargetHub server and Agent runtime are physically deployed.
