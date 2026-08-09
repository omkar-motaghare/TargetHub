# TargetHub Local Development with Docker

This is the standard local development and verification path for TargetHub.

## Prerequisites

- Git
- Docker Desktop (Windows/macOS) or Docker Engine + Docker Compose plugin (Linux)

Python and a local Python virtual environment are **not required** for the standard development workflow.

## 1. Get the latest `develop` branch

```bash
git checkout develop
git pull origin develop
```

Confirm the branch:

```bash
git branch --show-current
git log -1 --oneline
```

## 2. Optional: create a local environment file

Copy the example file:

```bash
cp .env.example .env
```

On Windows PowerShell:

```powershell
Copy-Item .env.example .env
```

For local development, the Compose file also provides a development-only default secret, so `.env` is optional.

Do not commit a real secret to Git.

## 3. Build and start TargetHub

From the repository root:

```bash
docker compose up --build
```

The container automatically runs the Alembic migrations before starting FastAPI/Uvicorn.

TargetHub is then available at:

- Dashboard: http://localhost:8000/dashboard
- API documentation: http://localhost:8000/docs
- API root: http://localhost:8000/

## 4. Run in the background

For the normal developer workflow:

```bash
docker compose up --build -d
```

Check the container:

```bash
docker compose ps
```

View logs:

```bash
docker compose logs -f targethub
```

## 5. Verify the application

Open the dashboard:

```text
http://localhost:8000/dashboard
```

Open Swagger:

```text
http://localhost:8000/docs
```

Check the API root:

```bash
curl http://localhost:8000/
```

Expected response is similar to:

```json
{
  "application": "TargetHub",
  "version": "0.1.0",
  "status": "running"
}
```

Check targets:

```bash
curl http://localhost:8000/api/v1/targets
```

Check reservations:

```bash
curl http://localhost:8000/api/v1/reservations
```

## 6. Stop TargetHub

```bash
docker compose down
```

The database remains in the named Docker volume `targethub_data`.

To remove the application container **and** the local database volume:

```bash
docker compose down -v
```

Use `down -v` only when you intentionally want to reset the local database.

## 7. Rebuild after code changes

When source or dependency changes require a new image:

```bash
docker compose up --build -d
```

To force a completely fresh image build:

```bash
docker compose build --no-cache
docker compose up -d
```

## 8. Database migrations

Migrations are applied automatically when the container starts:

```text
Container start
      |
      v
alembic upgrade head
      |
      v
uvicorn app.main:app
```

The SQLite database is stored in the Docker volume at `/data/targethub.db`.

Do not manually run Alembic from a host Python virtual environment for the normal Docker workflow.

## 9. Development workflow

The intended workflow is:

```text
Pull develop
    |
    v
Make code changes
    |
    v
Docker Compose rebuild
    |
    v
Open /dashboard and /docs
    |
    v
Verify feature
    |
    v
Commit to develop
```

## 10. Troubleshooting

### Container exits immediately

Inspect logs:

```bash
docker compose logs targethub
```

### Port 8000 is already in use

Stop the conflicting service or change the host-side port in `docker-compose.yml`, for example:

```yaml
ports:
  - "8080:8000"
```

Then use http://localhost:8080/dashboard.

### Reset local development data

```bash
docker compose down -v
docker compose up --build -d
```

This recreates the database from the current Alembic migrations.

## Architecture note

Docker is the standard local deployment mechanism for the current development workflow. The same containerized application model will also support the team-hosted deployment described by Architecture v1.0; the final production packaging and appliance image will be refined later.
