# Installing the Agent on a Raspberry Pi (aarch64)

> **Status:** the agent is stdlib-only Python and the installer/unit are tested on an x86_64 Linux dev host
> (installer `--prefix` dry run, `systemd-analyze verify`, live E2E with a pty serial loopback and a fake sysfs GPIO tree).
> It has **not** been run on real Raspberry Pi hardware yet. Treat the steps below as the intended procedure and
> report anything that differs on a real board.

## Requirements

- Raspberry Pi OS (Bookworm or later, 64-bit/aarch64 recommended; 32-bit armv7 should also work) or any systemd Linux.
- `python3` (3.9+), `curl`, `sha256sum`, `systemd`. No pip packages are needed.
- Outbound HTTPS to the hub. No inbound ports are opened.
- Optional for GPIO power control: the `gpiod` tools (`sudo apt install gpiod`) if you use the `gpiod` backend.

## Install

1. In the TargetHub UI open **Admin → Agents**, enter an agent name and create an enrollment (token valid 30 minutes, single use).
2. Run the displayed command on the Pi. It downloads the installer, checks its sha256, then runs it with the agent's expected sha256:

```bash
curl -fsSL https://<hub>/web/agent/install.sh -o targethub-install.sh
echo '<installer-sha256>  targethub-install.sh' | sha256sum -c -
sudo bash targethub-install.sh --targethub-url 'https://<hub>' \
  --enrollment-token '<one-time-token>' --agent-sha256 <agent-sha256>
```

The installer creates the `targethub` system user (added to `dialout`, `gpio`, `plugdev` when those groups exist),
installs `/opt/targethub-agent/targethub_agent.py`, writes `/etc/targethub-agent/<instance>.json` (mode 0600) and enables
`targethub-agent@<instance>.service`. Check it with:

```bash
systemctl status 'targethub-agent@*'
journalctl -u 'targethub-agent@*' -f
```

The unit sets `MemoryMax=64M`, `NoNewPrivileges`, `ProtectSystem=strict` and a 120 s watchdog.

## Declaring serial, power and deploy resources

Hardware is declared in the agent-local config (never accepted from the hub). Edit `/etc/targethub-agent/<instance>.json`
and add entries to `resources`, then `sudo systemctl restart targethub-agent@<instance>`:

```json
"resources": [
  {"resource_key": "/dev/ttyUSB0", "resource_type": "serial", "display_name": "DUT console",
   "metadata": {"path": "/dev/ttyUSB0", "baudrate": 115200, "timeout": 0.5}},
  {"resource_key": "power:relay1", "resource_type": "power", "display_name": "Relay 1",
   "metadata": {"backend": "gpiod", "chip": "gpiochip0", "line": 17, "active_low": true, "pulse_seconds": 0.5}},
  {"resource_key": "deploy:flash", "resource_type": "deploy", "display_name": "Flash",
   "metadata": {"command": ["cp", "{artifact}", "/media/dut/firmware.bin"]}}
]
```

Notes:

- Use the `sysfs` backend only on kernels that still expose `/sys/class/gpio`; Bookworm kernels generally need `gpiod`.
  On a Pi 5 the header GPIO chip is usually `gpiochip4` (`gpioinfo` lists chips and lines).
- `ReadWritePaths` in the unit allows `/sys/class/gpio`; the `gpiod` backend needs the `targethub` user in the `gpio` group.
- Prefer stable serial names such as `/dev/serial/by-id/...`; the agent discovers `ttyUSB*`, `ttyACM*` and by-id links.
- Wire relays/reset lines through proper drivers; a Pi GPIO pin must never switch a target supply directly.

## Uninstall

```bash
sudo systemctl disable --now 'targethub-agent@<instance>.service'
sudo rm /etc/systemd/system/targethub-agent@.service
sudo rm -r /opt/targethub-agent /etc/targethub-agent
```

Then revoke the agent in the UI.
