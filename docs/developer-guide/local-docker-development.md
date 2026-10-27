# Development guide

## Layout

| Path | What | Stack |
| --- | --- | --- |
| `backend/app` | API, services, repositories, providers, scheduler | Python 3.12, FastAPI, SQLAlchemy 2, Alembic, Pydantic 2 |
| `backend/app/web/agent` | Agent (`targethub_agent.py`) and its installers (`install.sh`, `install.ps1`) | Python 3.9+ stdlib (+ pyserial on Windows) |
| `backend/tests` | Unit, API, migration, installer and live-agent end-to-end tests | pytest |
| `frontend` | Web UI | React 18, react-router 7, Vite 7, xterm.js, Vitest, Playwright |
| `sdk/python` | SDK and `targethub` CLI | httpx |
| `vscode-extension` | VS Code extension | TypeScript |
| `tools` | DD mock, virtual board, demo lab | stdlib Python |

Key backend concepts:

- **Reservation** (who owns a target, when) → **Session** (one capability of a reserved target) →
  **operation** (power `on`, serial `read`, `deploy`, …) executed by a **provider**.
- Providers run on the server (DD, HTTP power, HTTP bridges) or are proxied to an **agent** through the
  `agent_operations` queue (`services/agent_operation_service.py`). Agents long-poll; claims are atomic
  conditional updates; in-process signals wake waiters immediately.
- The serial console WebSocket (`api/v1/serial_ws.py`) pumps agent reads into the socket and writes input back.
- `services/scheduler.py` runs maintenance every 30 s in each worker: expiry, ending-soon warnings, waitlist,
  agent liveness, retention. Every step is idempotent.

## Run everything from source

```bash
bash scripts/bootstrap-backend.sh                  # backend/.venv with runtime + test deps
cd backend
export SECRET_KEY=dev-secret-key-that-is-long-enough ENVIRONMENT=development ADMIN_BOOTSTRAP_TOKEN=dev
.venv/bin/alembic upgrade head                     # SQLite targethub.db by default
.venv/bin/uvicorn app.main:app --reload --port 8000

cd ../frontend && npm ci && npm run dev            # http://localhost:5173, proxies /api to :8000
```

`ENVIRONMENT=development` enables simulated providers. Start the [demo lab](../development/simulators.md)
for realistic hardware without boards.

## Tests

```bash
# Backend (≈250 tests, ~1 min). Set TARGETHUB_PWSH to run PowerShell installer tests too.
backend/.venv/bin/python -m pytest -q backend/tests
backend/.venv/bin/ruff check backend/app backend/tests tools sdk/python --config backend/pyproject.toml

# Live end-to-end: real server + real agent process + pty serial loopback
bash scripts/e2e-agent.sh

# Frontend
cd frontend && npm run typecheck && npm test && npm run build

# Browser smoke (builds the SPA, starts a server, drives Chrome with Playwright)
PLAYWRIGHT_CHANNEL=chrome bash scripts/e2e-ui.sh       # or PLAYWRIGHT_CHROMIUM_PATH=/path/to/chrome

# SDK and VS Code extension
cd sdk/python && pip install -e ".[test]" && pytest -q
cd vscode-extension && npm ci && npm run compile && npm test && npm run package
```

CI (`.github/workflows/ci.yml`) runs all of these plus PostgreSQL migrations, Windows agent/installer tests
and a Docker build-and-boot check. `release.yml` publishes the multi-arch image and release assets on
`v*` tags.

## Database migrations

```bash
cd backend
.venv/bin/alembic revision -m "describe change"   # write upgrade() and downgrade() by hand
.venv/bin/alembic upgrade head && .venv/bin/alembic downgrade -1 && .venv/bin/alembic upgrade head
```

Update `EXPECTED_HEAD` in `tests/test_migrations_lifecycle.py`. Use the `UTCDateTime` column type for
timestamps (SQLite otherwise drops the timezone).

## Docker

```bash
docker compose up -d --build          # needs .env; scripts/install.sh --no-start creates one
docker compose logs -f api
```

## Conventions

- Business rules live in services; routes stay thin; repositories own queries.
- Never put secrets in `provider_config`; reference environment variable names.
- Anything an agent executes must be declared in the agent's local config.
- New features come with tests and a docs update; user-visible changes go in `CHANGELOG.md`.
