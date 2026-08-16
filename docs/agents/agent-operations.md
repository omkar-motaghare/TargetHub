# TargetHub Agent Operations

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
- installs the Agent under `/opt/targethub-agent`;
- stores per-enrollment configuration under `/etc/targethub-agent/` with mode `0600`;
- creates the templated `targethub-agent@.service`;
- enables and starts the specific enrollment instance.

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

If an Agent credential is revoked or the Agent is disabled, create a new enrollment using the **same Agent name** to restore that Agent identity with a new credential. The existing active credential is never replaced merely by creating an enrollment; active Agent names remain protected from accidental credential replacement.

If an enrollment token expires or is consumed, create another enrollment rather than reusing the old token.
