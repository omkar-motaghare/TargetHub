# TargetHub Agent Deployment & Onboarding Architecture

## Status

**Architecture Decision / Design Baseline**

This document records the deployment and onboarding model for TargetHub Agents so that the implementation remains consistent across the supported lab topologies.

The design extends the existing TargetHub architecture baseline, where the Server and Agent are separate logical components and may be colocated, and where an Agent owns the physical resources available on a host.

---

## 1. Goals

The Agent architecture must allow a Team Administrator to configure hardware connectivity without requiring the administrator to understand Linux device paths, provider-specific JSON, or internal database identifiers.

The design must support:

1. TargetHub Server and Agent on the same Linux machine.
2. TargetHub Server on one Linux machine and Agent on a remote Raspberry Pi near the hardware.
3. TargetHub Server and Agent both running on a single Raspberry Pi.
4. Multiple Agents managed by one TargetHub installation.
5. Agents being added and replaced without manually editing database records.
6. Agent resource discovery being visible in the Web UI.
7. Secure Agent-to-Server authentication.
8. Reconnection and heartbeat handling when an Agent temporarily disappears.
9. Future support for additional provider/resource types without changing the administrator workflow.

---

## 2. Core Principle

**The Team Administrator configures logical hardware in the Web UI; the Agent discovers physical hardware.**

The administrator should never normally need to enter values such as:

- `/dev/ttyUSB0`
- `/dev/ttyACM0`
- J-Link serial numbers
- provider-specific JSON
- internal `agent_id` values
- internal `resource_id` values

Instead, the Web UI presents human-readable Agents and resources discovered by those Agents.

Example:

```text
Target: BOARD-01

Capability: Serial Console

Agent:
  lab-pi-01

Detected resource:
  USB Serial — ST-Link Virtual COM Port

[ Save capability ]
```

The backend may persist provider-specific configuration internally, but it is not part of the normal administration workflow.

---

## 3. Logical Architecture

```text
                         Team Administrator
                                |
                                v
                       +-------------------+
                       | TargetHub Web UI  |
                       +---------+---------+
                                 |
                                 v
                       +-------------------+
                       |  TargetHub Server  |
                       |                   |
                       | Auth / RBAC       |
                       | Target Management |
                       | Reservations      |
                       | Sessions          |
                       | Agent Registry    |
                       | Resource Registry |
                       +---------+---------+
                                 |
                    Agent control / heartbeat
                                 |
                +----------------+----------------+
                |                                 |
                v                                 v
       +------------------+              +------------------+
       | TargetHub Agent  |              | TargetHub Agent  |
       | lab-linux-01     |              | lab-pi-01        |
       +--------+---------+              +--------+---------+
                |                                 |
                v                                 v
        Local hardware                    Remote hardware
```

The Agent boundary is intentionally independent of the physical location of the Server.

---

## 4. Supported Deployment Scenarios

### Scenario A — Linux Server and Agent on the Same Machine

A team already has an always-on Linux workstation/server connected directly to the embedded hardware.

```text
+--------------------------------------------------+
| Linux Machine                                    |
|                                                  |
|  +-------------------+                           |
|  | TargetHub Server  |                           |
|  +-------------------+                           |
|                                                  |
|  +-------------------+                           |
|  | TargetHub Agent   |                           |
|  +---------+---------+                           |
|            |                                     |
|            v                                     |
|      USB / Serial / J-Link / other hardware      |
+--------------------------------------------------+
```

The Web UI shows the Agent as a local Agent. No special administrator workflow is required.

Recommended deployment:

- Run Server and Agent as separate logical services.
- They may share the same Docker host.
- Agent communicates with Server through the normal Agent API/channel.
- Hardware devices remain accessible only to the Agent process.

This preserves the architectural separation while avoiding unnecessary network hardware.

---

### Scenario B — Server on Linux, Agent on Remote Raspberry Pi

The TargetHub Server runs on an existing Linux machine, while the hardware is physically located elsewhere.

```text
                 LAN / VPN

+--------------------------+       +--------------------------+
| Linux Server             |       | Raspberry Pi             |
|                          |       |                          |
| TargetHub Server         |<----->| TargetHub Agent          |
| Database                 |       |                          |
| Web UI                   |       | USB / UART / J-Link      |
+--------------------------+       +------------+-------------+
                                                |
                                                v
                                          Embedded Hardware
```

This is the preferred model when hardware is physically distributed away from the central server.

The Agent should establish the connection to the Server rather than requiring the Server to initiate arbitrary inbound connections to the Raspberry Pi. This makes the deployment simpler behind NAT/firewalls and reduces exposed network services.

The Agent continuously reports:

- Agent identity
- hostname
- software version
- online/offline state
- last heartbeat
- discovered resources
- resource availability
- resource metadata

---

### Scenario C — Raspberry Pi Runs Both Server and Agent

A team does not have a dedicated Linux server and uses one Raspberry Pi as the complete TargetHub appliance.

```text
+--------------------------------------------------+
| Raspberry Pi                                     |
|                                                  |
|  +-------------------+                           |
|  | TargetHub Server  |                           |
|  | Web UI + API      |                           |
|  +-------------------+                           |
|                                                  |
|  +-------------------+                           |
|  | TargetHub Agent   |                           |
|  +---------+---------+                           |
|            |                                     |
|            v                                     |
|      USB / Serial / J-Link / hardware            |
+--------------------------------------------------+
```

The Web UI remains identical to Scenario A.

The installation experience should be appliance-oriented: install the TargetHub stack, open the Web UI, complete initial setup, and the local Agent should be available for resource discovery.

---

## 5. Administrator Onboarding Workflow

The administrator should not manually create an Agent database record.

The intended workflow is:

```text
Admin opens TargetHub
        |
        v
Administration -> Agents
        |
        v
[ Add Agent ]
        |
        v
Choose deployment method
        |
        +----------------------+----------------------+
        |                      |                      |
        v                      v                      v
Same host              Remote Linux/Pi          Appliance/local
        |                      |                      |
        +----------------------+----------------------+
                               |
                               v
                    Generate one-time setup token
                               |
                               v
                     Install / start Agent
                               |
                               v
                     Agent authenticates
                               |
                               v
                     Agent sends heartbeat
                               |
                               v
                   Agent appears as ONLINE
                               |
                               v
                     Resources discovered
                               |
                               v
                   Admin maps resources to
                   Target capabilities
```

### Important UX rule

The setup process should be guided by the Web UI. The administrator should be given an exact installation command or configuration snippet generated for that specific Agent.

For example:

```text
Agent name: lab-pi-01

1. Install TargetHub Agent on the Raspberry Pi.
2. Run the generated setup command.
3. Return to this page.
4. Wait for the Agent to become ONLINE.
5. Configure discovered resources.
```

The actual command format is an implementation detail and must not be hard-coded into this architecture document.

---

## 6. Agent Identity and Pairing

Every Agent requires a unique persistent identity.

The recommended lifecycle is:

```text
Admin creates Agent registration
        |
        v
Server creates:
  - agent_id
  - one-time enrollment credential
  - display name
        |
        v
Admin installs Agent
        |
        v
Agent presents enrollment credential
        |
        v
Server validates credential
        |
        v
Server binds Agent installation to agent_id
        |
        v
Enrollment credential becomes invalid
        |
        v
Agent uses its persistent authentication credential
```

### Security requirements

- Enrollment credentials must be short-lived or one-time use.
- Persistent Agent credentials must be stored securely on the Agent host.
- Credentials must never be displayed again in plaintext after enrollment where practical.
- Agent credentials must be revocable from the Web UI.
- Revoking an Agent must immediately prevent further authenticated Agent communication.
- Agent names are human-readable labels and must not be used as authentication credentials.

A future implementation may use mutual TLS or another equivalent authenticated transport, but the architecture does not require a specific cryptographic mechanism yet.

---

## 7. Agent States

The Web UI should expose clear Agent lifecycle states.

```text
                    +-------------+
                    |  REGISTERED |
                    +------+------+ 
                           |
                           v
                    +-------------+
                    |  ENROLLING  |
                    +------+------+ 
                           |
                           v
                    +-------------+
                    |    ONLINE   |
                    +------+------+ 
                           |
              heartbeat timeout
                           |
                           v
                    +-------------+
                    |   OFFLINE   |
                    +------+------+ 
                           |
                    reconnect
                           |
                           v
                    +-------------+
                    |    ONLINE   |
                    +-------------+
```

Additional administrative states may be added later:

- Disabled
- Revoked
- Upgrade required
- Error

The distinction between **offline** and **revoked/disabled** is important. An offline Agent may simply be temporarily unavailable, while a revoked Agent is no longer trusted to communicate with the Server.

---

## 8. Resource Discovery

The Agent is responsible for discovering physical resources on its host.

Examples include:

```text
Agent: lab-pi-01

Discovered resources
--------------------
Serial
  USB Serial — /dev/ttyUSB0
  USB Serial — /dev/ttyACM0

Debugger
  J-Link — serial 123456789

Network
  Ethernet interface
```

The Agent should expose a stable resource identity that is not dependent solely on a transient Linux device path.

For example, `/dev/ttyUSB0` may change after a reboot, while a stable hardware identifier or provider-specific identity can remain constant.

The architecture therefore distinguishes:

```text
resource_id / stable resource key
        |
        +--> physical device path
        +--> human-readable name
        +--> provider type
        +--> metadata
        +--> availability
```

The Web UI should display the human-readable identity and relevant metadata while keeping low-level implementation details optional.

---

## 9. Mapping Agents to Targets

A Target is a logical resource. A Capability describes how the Target can be accessed. An Agent owns the physical resource used to implement that capability.

```text
Target
  |
  +-- Serial Console
  |      |
  |      +-- Agent: lab-pi-01
  |      +-- Resource: USB Serial #1
  |
  +-- Debugger
         |
         +-- Agent: lab-pi-01
         +-- Resource: J-Link #12345
```

This allows one Target to use multiple physical resources and allows one Agent to service multiple Targets, subject to resource ownership and provider constraints.

The administrator workflow is therefore:

```text
Targets
  -> Select target
  -> Capabilities
  -> Add capability
  -> Select Agent
  -> Select discovered resource
  -> Save
```

---

## 10. Multiple Agents

A single TargetHub Server may manage many Agents.

Example:

```text
TargetHub Server
 |
 +-- lab-linux-01
 |      +-- Serial #1
 |      +-- J-Link #1
 |
 +-- lab-pi-01
 |      +-- Serial #1
 |      +-- Serial #2
 |
 +-- lab-pi-02
        +-- Serial #1
        +-- Power controller
```

The Agent list should provide:

- Name
- Hostname
- Status
- Last seen
- Version
- Resource count
- Enable/disable state
- Enrollment/revocation controls

Selecting an Agent should show its discovered resources and their current status.

---

## 11. Agent Replacement and Recovery

Agents are expected to be replaceable.

Example:

```text
Old Raspberry Pi
Agent: lab-pi-01
        |
        | hardware failure
        v
New Raspberry Pi
        |
        v
Re-enroll / replace Agent installation
        |
        v
lab-pi-01 restored
```

The design should avoid tying Target configuration directly to a Raspberry Pi hostname or IP address.

Target capability mappings should reference the logical Agent/resource identity. Replacement workflows can then explicitly migrate or rebind the Agent/resource mapping.

A future Web UI action may be:

```text
Agent: lab-pi-01

[ Replace Agent Installation ]
```

which generates a new enrollment process while preserving the administrator's logical configuration where the replacement resources can be matched safely.

---

## 12. Network and Connectivity Model

The preferred communication pattern is:

```text
Agent  --->  TargetHub Server
```

rather than requiring:

```text
TargetHub Server  --->  Agent inbound listener
```

Reasons:

- simpler firewall configuration
- easier Raspberry Pi deployment
- better support for private lab networks
- reduced number of exposed services
- easier NAT traversal in common deployments

The exact transport may be HTTP(S), WebSocket, or another authenticated channel depending on the implementation stage. The architecture requires authenticated communication, heartbeat semantics, and reconnect behavior but does not lock the project to one transport prematurely.

---

## 13. Failure Handling

### Agent offline

When heartbeats stop:

1. Server marks Agent as offline after the configured timeout.
2. Existing resource states are no longer considered freshly verified.
3. UI clearly indicates the Agent is offline.
4. New operations requiring that Agent are rejected or unavailable.
5. Existing sessions using that Agent follow the session failure policy.
6. When the Agent reconnects, it re-registers/heartbeats and refreshes resource state.

### Server unavailable

The Agent should tolerate temporary Server unavailability without corrupting local state. The exact offline behavior of hardware control operations must be defined by the provider/session security model before implementation.

### Resource disappears

If a USB device is unplugged:

```text
Agent remains ONLINE
        |
        v
Resource becomes UNAVAILABLE
```

The Agent itself should not be marked offline merely because one physical resource disappeared.

---

## 14. Web UI Information Architecture

The administration UI should expose the following concepts.

### Agents page

```text
Administration
  |
  +-- Agents
        |
        +-- Add Agent
        +-- Agent list
        +-- Agent details
        +-- Resources
        +-- Disable
        +-- Revoke
        +-- Replace installation
```

### Add Agent wizard

Recommended steps:

```text
1. Name Agent
2. Choose deployment location
3. Generate enrollment instructions
4. Install/start Agent
5. Wait for connection
6. Verify Agent identity
7. Review discovered resources
8. Finish
```

### Target capability configuration

```text
Target -> Capabilities -> Add/Edit

Capability type
      |
      v
Agent
      |
      v
Discovered resource
      |
      v
Provider-specific settings (advanced/internal where required)
```

This separates **Agent onboarding** from **Target configuration**.

---

## 15. What the Administrator Should Not Need to Know

The following are implementation details and should normally be hidden from the team administrator:

- SQLAlchemy model names
- database primary keys
- provider class names
- Python package names
- `/dev/*` paths as the only identifier
- raw provider JSON
- Docker container IDs
- internal API implementation details

The administrator should work with:

- Agent name
- Hostname
- Online/offline status
- Resource display name
- Resource type
- Target name
- Capability name
- Hardware metadata relevant to selection

---

## 16. Implementation Boundaries

The architecture should be implemented incrementally.

### Already established

- Agent registry
- Agent resource model
- Server-side Agent/resource APIs
- Web UI Agent/resource selection for target capabilities

### Next Agent increment

Implement the physical Agent runtime that:

1. starts on Linux/Raspberry Pi;
2. enrolls with the Server;
3. authenticates using its persistent credential;
4. sends heartbeat;
5. discovers local resources;
6. reports resource state;
7. reconnects automatically;
8. supports controlled shutdown and restart.

### Later increments

- Serial transport through the Agent
- Power/reset provider integration
- J-Link provider integration
- Network/SSH/Telnet/FTP enforcement
- Agent upgrade management
- Agent replacement workflow
- Multi-Agent scheduling/health views

---

## 17. Architecture Decision Summary

The following decisions are considered the baseline for future implementation:

1. **Server and Agent remain separate logical components even when colocated.**
2. **An Agent owns physical resources; a Target owns logical capabilities.**
3. **Team Administrators configure Agents through the Web UI rather than editing database records.**
4. **The Agent performs physical resource discovery.**
5. **Target capability configuration selects an Agent and discovered resource.**
6. **Agent enrollment uses a one-time setup credential followed by persistent Agent authentication.**
7. **Agent-to-Server outbound connectivity is preferred.**
8. **The same Web UI workflow must support central-server, remote-Raspberry-Pi, and all-in-one-Raspberry-Pi deployments.**
9. **Agent identity must not depend on hostname or IP address.**
10. **Agent/resource availability is dynamic and must be reflected in the Web UI.**
11. **Agent replacement must be possible without rebuilding the logical Target model.**
12. **Provider-specific implementation details remain behind the Agent/provider boundary.**

---

## 18. Reference User Journey

A complete future onboarding journey should look like this:

```text
Team Admin
   |
   | Open TargetHub
   v
Administration -> Agents -> Add Agent
   |
   | Enter: lab-pi-01
   v
TargetHub generates enrollment instructions
   |
   | Admin installs Agent on Raspberry Pi
   v
Agent connects to TargetHub
   |
   v
Agent ONLINE
   |
   v
Agent discovers:
  - USB Serial #1
  - J-Link #1
   |
   v
Admin opens Targets -> BOARD-01
   |
   v
Add capability -> Serial Console
   |
   v
Select Agent -> lab-pi-01
   |
   v
Select resource -> USB Serial #1
   |
   v
Save
   |
   v
BOARD-01 is now logically connected
   |
   v
Developer reserves BOARD-01
   |
   v
TargetHub authorizes session
   |
   v
Agent performs controlled hardware access
```

This is the intended end-state for self-service team administration of TargetHub Agents.