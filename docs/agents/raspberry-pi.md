# Raspberry Pi as a lab agent

A Raspberry Pi 4 or 5 makes a good agent: it sits next to the boards, takes USB-serial adapters and a relay
HAT, and needs only outbound network access. Follow the [agent guide](agent-guide.md); this page lists
the Pi-specific details.

## Prepare the Pi

- Raspberry Pi OS Bookworm (64-bit recommended; 32-bit armv7 also works), or any systemd Linux such as Ubuntu or Yocto.
- `sudo apt install python3 curl gpiod`. No pip packages are needed.
- Give it a stable hostname and a DHCP reservation, and keep the clock synced (`timedatectl`). Reservation
  times and TLS both depend on it.
- Prefer a powered USB hub for several USB-serial adapters.

## Install

Run the **Linux** enrollment command from **Admin → Agents**. The installer:

- creates the `targethub` system user and adds it to `dialout`, `gpio` and `plugdev` when they exist;
- installs `/opt/targethub-agent/targethub_agent.py` and `/etc/targethub-agent/<instance>.json` (0600);
- enables `targethub-agent@<instance>.service` (hardened: `NoNewPrivileges`, `ProtectSystem=strict`,
  `MemoryMax=64M`, 120 s watchdog);
- works on minimal/BusyBox images without `curl`, `useradd` or `getent` (falls back to `wget`/Python and `adduser`).

## GPIO relays

```bash
gpioinfo                     # list chips and lines
gpioset gpiochip0 17=1       # libgpiod v1 syntax; quick manual relay test
```

- Pi 4 and earlier: header GPIOs are on `gpiochip0`. Pi 5: usually `gpiochip4` (check `gpioinfo`).
- Use `"backend": "gpiod"`. The legacy `sysfs` interface is gone on current kernels.
- Most relay HATs are active-low (`"active_low": true`).
- Never switch a target's supply directly from a GPIO pin; use a relay board or driver stage.

## Serial

Use the stable names under `/dev/serial/by-id/`. The Pi's own UART (`/dev/ttyAMA0`, `/dev/serial0`) can be
declared too; disable the serial login console first (`raspi-config` → Interface → Serial: login shell
*No*, hardware *Yes*).

## Running the TargetHub server on a Pi

The published image is multi-arch (`linux/arm64`), so a Pi 5 with 4 GB+ RAM and an SSD can host a small
lab's server too: install Docker (`curl -fsSL https://get.docker.com | sh`) and use
`scripts/install.sh --image ghcr.io/omkar-motaghare/targethub:0.2.0`.

## Verification status

The agent was verified on a Raspberry Pi 5 (Yocto, read-only NFS root) for enrollment, discovery, pty
serial, fake-GPIO power, restart and offline detection in 0.1.0. The 0.2.0 agent (concurrent operations,
buffered serial, DD fallback) is tested on x86_64 Linux and with simulators. Please run the
[manual verification checklist](../MANUAL_VERIFICATION_CHECKLIST.md) on a real Pi with a relay and a board.
