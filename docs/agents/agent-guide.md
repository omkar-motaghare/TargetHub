# Agents: Linux, Raspberry Pi and Windows

An **agent** runs on a machine that has boards physically attached (USB-serial adapters, relay HATs,
flashing probes). It connects **out** to the TargetHub server, reports what it has, and executes serial,
power and deploy operations for the session that owns the board.

You do not need an agent for reservations or for DD / HTTP power; those run on the server.

| | Linux (x86_64, arm64) / Raspberry Pi OS | Windows 10/11, Server 2019+ |
| --- | --- | --- |
| Runtime | Python 3.9+ (standard library only) | Python 3.10+ from python.org, plus `pyserial` (installed automatically) |
| Runs as | systemd service `targethub-agent@<instance>` as user `targethub` | Scheduled Task "TargetHub Agent <instance>" as SYSTEM, restarts on failure |
| Config | `/etc/targethub-agent/<instance>.json` (0600) | `C:\ProgramData\TargetHub\agent\<instance>.json` (Administrators/SYSTEM only) |
| Logs | `journalctl -u 'targethub-agent@*'` | `C:\ProgramData\TargetHub\agent\<instance>.log` |
| Serial | `/dev/ttyUSB*`, `/dev/ttyACM*`, `/dev/serial/by-id/*` | `COM*` ports |
| Power | GPIO relays (sysfs or libgpiod), DD fallback | DD fallback (no GPIO) |
| Deploy | any local command | any local command |

Network: the agent needs outbound HTTPS to the server URL only. No inbound ports, so it works behind NAT
and corporate firewalls.

## 1. Enroll

1. **Admin → Agents** → enter a name (e.g. `rack2-pi`) → **Create enrollment**.
2. Copy the command for your platform. It is valid for 30 minutes and can be used once. It downloads the
   installer from your server, verifies its SHA-256, and installs the agent with the agent's expected SHA-256.

**Linux / Raspberry Pi** (needs `sudo`, `python3`, `curl` or `wget`, `sha256sum`):

```bash
curl -fsSL https://hub.example.com/web/agent/install.sh -o targethub-install.sh
echo '<installer-sha256>  targethub-install.sh' | sha256sum -c -
sudo bash targethub-install.sh --targethub-url 'https://hub.example.com' \
  --enrollment-token '<one-time-token>' --agent-sha256 <agent-sha256>
```

**Windows** (elevated PowerShell, *Run as administrator*; Python 3.10+ installed *for all users*):

```powershell
$f="$env:TEMP\targethub-install.ps1"; Invoke-WebRequest -UseBasicParsing 'https://hub.example.com/web/agent/install.ps1' -OutFile $f;
if ((Get-FileHash $f -Algorithm SHA256).Hash -ne '<installer-sha256>') { throw 'installer checksum mismatch' };
powershell -NoProfile -ExecutionPolicy Bypass -File $f -TargetHubUrl 'https://hub.example.com' `
  -EnrollmentToken '<one-time-token>' -AgentSha256 <agent-sha256>
```

Extra installer options: `-Python <path to python.exe>`,
`-InstallDir`, `-ConfigDir`, `-SkipPyserial`, `-AllowInsecureHttp`.

If the server URL is plain `http://` (closed lab network), the generated commands include
`--allow-insecure-http` / `-AllowInsecureHttp`. Use HTTPS for anything else.

3. Within ~15 s the agent shows as **online** in **Admin → Agents** with its discovered serial ports.

Several agents can run on one host (one enrollment each); each gets its own instance, config and service.

## 2. Declare hardware

Discovered serial ports are reported automatically. Everything that **acts** on hardware (relays, deploy
commands) must be declared in the agent's local config. The server cannot add or change it. Edit the
config file, then restart the agent (see [Service management](#service-management)).

```json
{
  "targethub_url": "https://hub.example.com",
  "agent_id": "…written at enrollment…",
  "credential": "…written at enrollment…",
  "resources": [
    {"resource_key": "/dev/serial/by-id/usb-FTDI_FT232R_A50285BI-if00-port0", "resource_type": "serial",
     "display_name": "STM32-01 console", "metadata": {"baudrate": 115200}},

    {"resource_key": "power:relay1", "resource_type": "power", "display_name": "STM32-01 supply relay",
     "metadata": {"backend": "gpiod", "chip": "gpiochip0", "line": 17, "active_low": true, "pulse_seconds": 3}},

    {"resource_key": "deploy:stm32-01", "resource_type": "deploy", "display_name": "Flash STM32-01",
     "metadata": {"command": ["st-flash", "--reset", "write", "{artifact}", "0x8000000"], "timeout": 300}}
  ]
}
```

On Windows a serial entry looks like `{"resource_key": "COM5", "resource_type": "serial", "metadata": {"path": "COM5", "baudrate": 115200}}`.

### Serial

- Prefer `/dev/serial/by-id/...` paths on Linux so a board keeps its name across reboots and replugging.
- `baudrate` (default 115200). Supported: 1200 to 921600.
- Only discovered or configured ports can be opened. The agent refuses any other path.
- One session owns a port at a time. When a session ends (release, expiry, close), the agent closes the
  port. Ports idle for `serial_idle_timeout` seconds (default 900) are closed too.
- The `targethub` user is added to `dialout` automatically on Linux.

### Power (GPIO relays, Linux)

| Key | Meaning |
| --- | --- |
| `backend` | `gpiod` (libgpiod tools `gpioset`/`gpioget`, recommended on current kernels) or `sysfs` (legacy `/sys/class/gpio`) |
| `chip`, `line` | GPIO chip and line offset (`gpioinfo` lists them; on a Pi 5 the header is usually `gpiochip4`, on Pi 4 `gpiochip0`) |
| `active_low` | `true` if the relay energises on a low level |
| `pulse_seconds` | off-time for *cycle* (0.05 to 10 s) |
| `kind` | `reset_line` if the line drives a reset pin instead of a supply relay |
| `gpiod_version` | `2` (default) or `1` for older libgpiod tools |

Drive relays through a proper relay board or transistor stage. A GPIO pin must never switch a target supply
directly. Install `gpiod` with `sudo apt install gpiod`.

### Power through DD from an agent (fallback)

DD power normally runs **on the server** (recommended; see [DD power](../power/dd-power.md)). Only if the
server cannot reach the DD network, declare it on an agent that can:

```json
{"resource_key": "power:dd-n1-e2", "resource_type": "power", "display_name": "DD node 1 / endpoint 2",
 "metadata": {"backend": "dd", "base_url": "http://dd-server:5003", "hub_mac": "AA:BB:CC:DD:EE:FF",
              "node_id": 1, "endpoint": 2, "api_key_env": "TARGETHUB_DD_API_KEY", "cycle_delay": 3}}
```

The key is read from the agent's environment (`api_key_env`). It is never sent to the server. On Linux add
`Environment=TARGETHUB_DD_API_KEY=…` with `sudo systemctl edit targethub-agent@<instance>`. On Windows set it
as a machine variable: `[Environment]::SetEnvironmentVariable('TARGETHUB_DD_API_KEY','…','Machine')`.

### Deploy

- `command` is a list (no shell). `{artifact}` is replaced with the downloaded, checksum-verified file.
- The artifact URL must be `https://` unless `"allow_http": true` is set for that resource.
- Maximum artifact size is 256 MiB; `timeout` 5 to 3600 s (default 300).
- Output (last 2000 characters) is returned to the user.
- Typical commands: `st-flash`, `openocd -f … -c "program {artifact} verify reset exit"`, `JLinkExe -CommanderScript …`,
  `esptool.py write_flash 0x0 {artifact}`, `nrfjprog --program {artifact} --reset`, or `cp {artifact} /media/DAPLINK/`.

## 3. Link resources to targets

In **Admin → Targets**, add a capability with backend **Agent hardware**, pick the agent and the
resource. Reserve the target and open a session to test it.

## Other settings

| Key | Default | |
| --- | --- | --- |
| `heartbeat_interval` | 15 | seconds between heartbeats (offline after 45 s without one) |
| `operation_poll_wait_seconds` | 10 | long-poll wait; operations start within milliseconds |
| `max_concurrent_operations` | 8 | operations run in parallel; power/deploy on the same resource are serialised |
| `serial_idle_timeout` | 900 | seconds before an unused port is closed |
| `request_timeout` | 15 | HTTP timeout to the server |
| `ca_bundle` | system store | PEM file for a private CA |
| `allow_insecure_http` | false | allow an `http://` server URL |

## Service management

```bash
# Linux
systemctl status 'targethub-agent@*'
sudo systemctl restart targethub-agent@<instance>
journalctl -u targethub-agent@<instance> -f
python3 /opt/targethub-agent/targethub_agent.py --version
```

```powershell
# Windows
Get-ScheduledTask -TaskName 'TargetHub Agent *' | Get-ScheduledTaskInfo
Stop-ScheduledTask  -TaskName 'TargetHub Agent <instance>'; Start-ScheduledTask -TaskName 'TargetHub Agent <instance>'
Get-Content C:\ProgramData\TargetHub\agent\<instance>.log -Tail 50 -Wait
```

## Upgrading an agent

Create a new enrollment for the same name after **Revoke credential**, or replace the agent file in
place: download `https://<server>/web/agent/targethub_agent.py`, check its SHA-256 against the
`--agent-sha256` value in a fresh enrollment command (or the release's `SHA256SUMS`), copy it over `/opt/targethub-agent/targethub_agent.py`
(Windows: `C:\Program Files\TargetHub\Agent\targethub_agent.py`) and restart. The agent version shows in
**Admin → Agents**.

## Uninstall

```bash
sudo systemctl disable --now 'targethub-agent@<instance>.service'
sudo rm /etc/systemd/system/targethub-agent@.service
sudo rm -r /opt/targethub-agent /etc/targethub-agent
```

```powershell
Unregister-ScheduledTask -TaskName 'TargetHub Agent <instance>' -Confirm:$false
Remove-Item -Recurse 'C:\Program Files\TargetHub\Agent', 'C:\ProgramData\TargetHub\agent'
```

Then **Revoke credential** for the agent in the UI.

## Security model

- Enrollment tokens are single use and expire after 30 minutes; the agent stores a long-lived credential
  in its 0600 / ACL-protected config and the server stores only its hash.
- The agent only executes `open/read/write/close` on allowed serial ports, `status/on/off/cycle/reset`
  on configured power resources and `deploy/status` on configured deploy resources, for the session that
  owns the resource. There is no remote shell.
- Private metadata (`command`, `api_key`, `api_key_env`, `password`, `token`) is never reported to the server.
- The Linux unit runs with `NoNewPrivileges`, `ProtectSystem=strict`, a memory cap and a watchdog.
