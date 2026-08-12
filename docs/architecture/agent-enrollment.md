# TargetHub Agent Enrollment Architecture

## Purpose

This document records the operator-friendly Agent enrollment flow. A Team Admin creates an Agent identity from the TargetHub Web UI, receives a short-lived installation command, and runs it on any supported Linux machine.

## Current implementation

The enrollment lifecycle provides:

- Agent identity and resource inventory persistence.
- Short-lived, single-use enrollment tokens stored as keyed hashes.
- Agent credential issuance and keyed-hash storage.
- Authenticated heartbeat using `Authorization: Bearer` credentials.
- Agent disable/enable and credential revocation.
- Web UI Agent administration and enrollment instructions.
- Dependency-free Linux Agent runtime.
- One-command installation through the TargetHub-hosted installer.
- Automatic serial/network resource discovery plus custom resource configuration.
- Multiple independent Agent instances on the same Linux host.

## Enrollment flow

The Web UI exposes an **Agents** administration area. A Team Admin supplies only a human-readable Agent name. TargetHub generates a short-lived, single-use enrollment token and a copyable installation command.

The administrator may run that command on any supported Linux machine. The Agent connects outbound to TargetHub, exchanges the enrollment token for a long-lived Agent credential, stores the credential locally, removes the enrollment token, and begins its heartbeat loop.

The normal lifecycle is:

1. Team Admin opens **Agents → Create enrollment**.
2. Admin gives the Agent a human-readable name.
3. TargetHub creates a pending enrollment and a one-time, expiring enrollment token.
4. UI shows copyable installation instructions.
5. Agent starts and calls the enrollment endpoint with the token and local hostname.
6. TargetHub validates the token, consumes it, and returns the Agent credential.
7. Agent stores the credential locally and starts its heartbeat loop.
8. TargetHub authenticates the heartbeat and updates discovered resources.
9. Web UI shows Agent status and resources.
10. Team Admin can disable/enable the Agent or revoke its credential.

## Platform policy

TargetHub does **not** bind an Agent to Raspberry Pi, x86 Linux, or another specific hardware class. The only platform requirement for the current Agent runtime is a supported Linux-based machine.

Examples include:

- Ubuntu/Debian workstation or server.
- Raspberry Pi running Raspberry Pi OS or another supported Linux distribution.
- Linux virtual machine.
- Other Linux-based embedded computers.

The Agent reports its hostname and discovered resources. Hardware identity is inferred from what the Agent can actually access rather than from an enrollment dropdown.

## Multiple Agents on one host

Each enrollment gets its own systemd instance and configuration derived from the enrollment token. Therefore multiple Agents may run independently on the same Linux machine, even though they share the same hostname.

For example:

```text
Linux host
├── Agent lab-agent-01
├── Agent lab-agent-02
└── Agent lab-agent-03
```

Each Agent has its own credential, heartbeat process, configuration, and resource inventory.

## Security properties

- Enrollment tokens are short-lived and single-use.
- Raw enrollment tokens are not stored in plaintext; TargetHub stores a keyed hash.
- Agent credentials are distinct from enrollment tokens and can be revoked independently.
- Raw Agent credentials are not returned by Agent listing/detail APIs.
- Disabled/revoked Agents are rejected by authenticated heartbeat calls.
- Heartbeat requires a valid Agent credential and verifies that the credential belongs to the URL Agent ID.
- The Agent makes outbound connections to TargetHub; TargetHub does not require inbound connectivity to the Agent for normal heartbeat operation.

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

## Important design decision

The Team Admin configures an Agent's identity from the TargetHub Web UI, but does **not** select a hardware or deployment scenario. Hardware/resource discovery belongs to the Agent. The Agent discovers and reports what is actually available on its Linux host.
