# TargetHub Agent Operations

## What is implemented

TargetHub now provides the complete first-version Agent enrollment lifecycle:

1. Team Admin creates an Agent enrollment from the Web UI.
2. TargetHub creates a 30-minute, single-use enrollment token.
3. The UI displays a copyable installation command.
4. The installer downloads the dependency-free Agent runtime and creates a systemd service.
5. The Agent exchanges the enrollment token for a long-lived Agent credential.
6. The token is removed from the Agent configuration after successful enrollment.
7. The Agent sends authenticated heartbeats every 15 seconds by default.
8. TargetHub stores the latest discovered resources.
9. Team Admin can see Agent status and resources in the Web UI.
10. Team Admin can disable/enable an Agent or revoke its credential.
11. Agents with no heartbeat for more than 45 seconds are shown as offline.

The raw enrollment token and raw Agent credential are never returned by Agent listing APIs. Each secret is displayed only at the point where it is issued.

## Deployment scenarios

### Scenario 1: TargetHub and Agent on the same Linux machine

Set `TARGETHUB_PUBLIC_URL` to a URL reachable by the Agent. For a Docker deployment where the Agent runs on the host, use the host's LAN address rather than `localhost` if the Agent must reach the published container port through the host network.

Example:

```text
TARGETHUB_PUBLIC_URL=http://192.168.1.50:8000
```

Open `/dashboard`, choose **Create enrollment**, select **TargetHub + Agent on same Linux machine**, and run the generated command on that Linux host.

### Scenario 2: TargetHub on Linux, Agent on remote Raspberry Pi

Set `TARGETHUB_PUBLIC_URL` to the TargetHub server's LAN address or DNS name reachable from the Raspberry Pi.

Example:

```text
TARGETHUB_PUBLIC_URL=http://192.168.1.50:8000
```

Create an enrollment for **TargetHub on Linux, Agent on remote Raspberry Pi**. Copy the generated command and run it on the Pi. The Pi initiates all Agent traffic outbound to TargetHub; TargetHub does not need inbound access to the Pi for heartbeat operation.

### Scenario 3: TargetHub and Agent on one Raspberry Pi

Set `TARGETHUB_PUBLIC_URL` to the Raspberry Pi's LAN address so that both local and remote administrators can use the same generated configuration.

Example:

```text
TARGETHUB_PUBLIC_URL=http://192.168.1.80:8000
```

Create an enrollment for **TargetHub + Agent on one Raspberry Pi** and run the generated command on that Pi.

## Agent installation

The generated command has this form:

```bash
curl -fsSL http://<targethub>/web/agent/install.sh | sudo bash -s -- \
  --targethub-url 'http://<targethub>' \
  --enrollment-token '<one-time-token>'
```

The installer:

- requires Python 3 and curl;
- installs the Agent under `/opt/targethub-agent`;
- stores configuration under `/etc/targethub-agent/config.json` with mode `0600`;
- creates `targethub-agent.service`;
- enables and starts the service.

Check the Agent with:

```bash
systemctl status targethub-agent
journalctl -u targethub-agent -f
```

## Resource discovery

The first runtime discovers:

- `/dev/ttyUSB*` serial resources;
- `/dev/ttyACM*` serial resources;
- `/dev/serial/by-id/*` stable serial resources;
- non-loopback Linux network interfaces;
- optional custom resources defined in the Agent configuration.

Hardware-specific discovery can be extended without changing the enrollment protocol.

## Credential lifecycle

Enrollment token:

- expires after 30 minutes;
- can be consumed once;
- is stored only as a keyed hash in TargetHub.

Agent credential:

- is issued only after successful enrollment;
- is stored only as a keyed hash in TargetHub;
- authenticates heartbeat calls with `Authorization: Bearer <credential>`;
- is independently revocable;
- becomes unusable when the Agent is disabled.

## Operational recovery

If an Agent credential is revoked, create a new enrollment for the same Agent name and run the new installation command on the Agent host. The existing Agent identity is reused and receives a new credential.

If an enrollment token expires or is consumed, create another enrollment rather than reusing the old token.
