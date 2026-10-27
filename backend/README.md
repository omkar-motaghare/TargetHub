## TargetHub Backend

This directory contains the canonical backend runtime package for TargetHub.

## Local validation

Use the repository-root bootstrap script to create or refresh the backend virtual environment and install the required runtime and test dependencies:

```bash
bash scripts/bootstrap-backend.sh
```

The recommended flow is to activate the venv first, then run the documented commands from inside `backend/`:

```bash
source .venv/bin/activate
cd backend
python -m pytest -q
python -m compileall -q app
```

If you prefer to avoid activating the environment, use the backend venv executable directly from the repository root:

```bash
backend/.venv/bin/python -m pytest -q backend/tests/
backend/.venv/bin/python -m compileall -q backend/app
```

To refresh an existing environment without activating it, rerun the bootstrap script:

```bash
bash scripts/bootstrap-backend.sh
```

## Runtime notes

- The backend package is `app` inside `backend/`.
- Docker builds from the `backend/` context.
- The web UI is the React app in `frontend/`; its build is served from `backend/app/web/react/` at `/app`.
- `backend/app/web/agent/` holds the agent and its installers, downloaded by enrollment commands from `/web/agent/`.
- `python -m app.manage --help` is the server-console admin tool (list users, reset passwords, create an admin).

## Authentication and first-admin bootstrap

`POST /api/v1/auth/users` requires an authenticated administrator. There is no
public self-registration endpoint.

To create the first admin account, set `ADMIN_BOOTSTRAP_TOKEN` (an environment
variable, unset/empty by default) before starting the backend, then call the
one-time bootstrap endpoint:

```bash
curl -X POST http://localhost:8000/api/v1/auth/bootstrap \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"change-me-now","bootstrap_token":"<ADMIN_BOOTSTRAP_TOKEN value>"}'
```

Bootstrap behavior:

- Returns `403` if `ADMIN_BOOTSTRAP_TOKEN` is not configured (bootstrap disabled by default).
- Returns `401` if the supplied `bootstrap_token` does not match.
- Returns `409` if an admin (or any user) has already been created; bootstrap is one-time only.
- On success, creates the first user with the `admin` role.

After bootstrapping, log in via `POST /api/v1/auth/token` and use the admin's
bearer token to create additional users via `POST /api/v1/auth/users`.

### Authorization summary

- `401 Unauthorized`: missing, malformed, invalid, or expired bearer token.
- `403 Forbidden`: valid token but insufficient role (e.g. non-admin calling an admin-only route).
- `409 Conflict`: valid, authorized request that conflicts with existing state (e.g. reservation/session ownership, duplicate bootstrap).

Admin-only endpoints include user creation, target and capability
administration, agent administration (list/detail/enroll-management/enable/
disable/revoke), and audit access. `POST /api/v1/agents/enroll` and
`POST /api/v1/agents/{id}/heartbeat` are intentionally reachable without a
TargetHub user token because Agents authenticate with their own enrollment
token / credential instead of a user account.

## Database lifecycle

Use Alembic from the backend environment:

```bash
source backend/.venv/bin/activate
cd backend
```

Check migration graph and current revision:

```bash
export SECRET_KEY=test-secret-key
python -m alembic heads
python -m alembic branches
python -m alembic current
```

Apply migrations:

```bash
export SECRET_KEY=test-secret-key
python -m alembic upgrade head
```

### Backup before migration (Docker Compose / PostgreSQL)

The canonical Docker stack uses PostgreSQL. Create a backup before migration:

```bash
docker compose exec -T postgres pg_dump -U targethub targethub > "targethub.backup.$(date +%Y%m%d%H%M%S).sql"
```

### Migration lifecycle checks

Run migration lifecycle tests:

```bash
source backend/.venv/bin/activate
python -m pytest -q backend/tests/test_migrations_lifecycle.py
```
