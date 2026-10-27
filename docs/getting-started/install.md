# Installation

TargetHub has two parts:

- **The server**: web UI, REST/WebSocket API and database. One per lab or team. It runs in Docker on Linux,
  Windows or macOS, including an ARM64 Raspberry Pi 4/5 when you use the published multi-arch image.
- **Agents** (optional): a small Python program on each machine that has boards plugged in. You need
  one only for serial consoles, GPIO relays or deploy commands. Teams that use TargetHub just for
  reservations and DD power control need no agents. See the [agent guide](../agents/agent-guide.md).

## Requirements

| | Minimum |
| --- | --- |
| Server host | 2 CPU, 2 GB RAM, 10 GB disk; Docker Engine 24+ with compose v2 (or Docker Desktop) |
| Network | Users and agents reach the server on one port (8000 by default, or 443 with TLS). Agents only make outbound connections. |
| Browsers | Current Chrome, Edge, Firefox or Safari |

## Linux or macOS server

```bash
git clone https://github.com/omkar-motaghare/TargetHub.git
cd TargetHub
scripts/install.sh --url http://lab-hub.example.local:8000
```

## Windows server (Docker Desktop)

Install and start Docker Desktop (WSL 2 backend), then from PowerShell:

```powershell
git clone https://github.com/omkar-motaghare/TargetHub.git
cd TargetHub
powershell -ExecutionPolicy Bypass -File scripts\install.ps1 -Url http://LAB-HUB:8000
```

Allow the port through Windows Defender Firewall if other machines must reach it:
`New-NetFirewallRule -DisplayName TargetHub -Direction Inbound -Protocol TCP -LocalPort 8000 -Action Allow`.

## Installer options

| install.sh | install.ps1 | Meaning | Default |
| --- | --- | --- | --- |
| `--url URL` | `-Url` | Public URL users **and agents** use. It is embedded in agent install commands. | `http://<host>:<port>` |
| `--port N` | `-Port` | Host port | `8000` |
| `--bind ADDR` | `-Bind` | Host address to publish on (`127.0.0.1` = this machine only) | `0.0.0.0` |
| `--project NAME` | `-Project` | Compose project name; change it to run several labs on one host | `targethub` |
| `--domain NAME` | `-Domain` | Enable the Caddy HTTPS overlay (ports 80/443, automatic certificates) | off |
| `--image REF` | `-Image` | Use a published image (e.g. `ghcr.io/omkar-motaghare/targethub:0.2.0`) instead of building | build from source |
| `--no-start` | `-NoStart` | Only write `.env` | |
| `--force` | `-Force` | Regenerate `.env` (secrets change; old file saved as `.env.bak`) | |

The installer writes `.env` with random `SECRET_KEY`, `POSTGRES_PASSWORD`, `ADMIN_BOOTSTRAP_TOKEN` and
`METRICS_TOKEN`, readable only by you. Running it again reuses `.env` and restarts the stack.
Every setting is documented in [`.env.example`](https://github.com/omkar-motaghare/TargetHub/blob/develop/.env.example).

## First login

1. Open `<url>/app`. A fresh server shows **Set up TargetHub**.
2. Paste the bootstrap token the installer printed (also in `.env` as `ADMIN_BOOTSTRAP_TOKEN`), choose an
   admin username and a password (8+ characters, not equal to the username).
3. The bootstrap token stops working as soon as the first user exists.

Lost the admin password? See [Administration → Recovering access](../admin-guide/administration.md#recovering-access).

## Using a published image

Tagged releases publish `ghcr.io/omkar-motaghare/targethub:<version>` for `linux/amd64` and `linux/arm64`.
You still need this repository (for `docker-compose.yml` and the scripts), but nothing is compiled:

```bash
scripts/install.sh --image ghcr.io/omkar-motaghare/targethub:0.2.0
```

## HTTPS

For anything beyond a closed lab network, serve TargetHub over HTTPS. Agents send long-lived credentials
and refuse plain `http://` unless explicitly allowed.

```bash
scripts/install.sh --domain hub.example.com      # Caddy + Let's Encrypt, needs public DNS
```

Behind your own reverse proxy, see [TLS and network exposure](../deployment/tls.md).

## Power systems and secrets

Secrets for power systems live **only in the server environment**, never in the database or UI. For the
DD power system add the key to `.env` and restart:

```bash
echo 'TARGETHUB_DD_API_KEY=<key from the DD administrator>' >> .env
docker compose up -d
```

Then follow [DD power](../power/dd-power.md).

## Day-2 commands

```bash
docker compose ps                          # status
docker compose logs -f api                 # server logs
docker compose up -d                       # apply .env changes
scripts/backup.sh backups/                 # database backup (see deployment/backup.md)
docker compose exec api python -m app.manage list-users
```

Upgrades and rollbacks: [Upgrade guide](../operations/upgrade.md).

## Running without Docker (evaluation or development)

Python 3.12 and Node 22:

```bash
cd frontend && npm ci && npm run build && cp -r dist ../backend/app/web/react && cd ..
bash scripts/bootstrap-backend.sh
cd backend
export SECRET_KEY=$(openssl rand -hex 32) ADMIN_BOOTSTRAP_TOKEN=$(openssl rand -hex 16)
export DATABASE_URL=sqlite:///./targethub.db
.venv/bin/alembic upgrade head
.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000
```

SQLite is fine for a single small team. Use PostgreSQL (the compose default) for production.
