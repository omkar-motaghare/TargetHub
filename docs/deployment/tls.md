# TLS and network exposure

Agents send long-lived credentials to the hub, so production hubs must be served over HTTPS.
The agent refuses `http://` hub URLs unless `allow_insecure_http` is set (lab/dev only).

## Caddy (automatic certificates)

```bash
export SECRET_KEY=$(openssl rand -hex 32) POSTGRES_PASSWORD=$(openssl rand -hex 16)
export TARGETHUB_DOMAIN=hub.example.com TARGETHUB_PUBLIC_URL=https://hub.example.com
docker compose -f docker-compose.yml -f docker-compose.tls.yml up -d --build
```

`docker-compose.tls.yml` adds a Caddy container on 80/443 with Let's Encrypt certificates,
removes the API's host port mapping, and returns 404 for `/metrics` on the public listener.
`docker/Caddyfile` sets HSTS and `nosniff`. Postgres, Redis and MinIO are bound to
`127.0.0.1` in the base compose files and need `POSTGRES_PASSWORD` to be set.

`TARGETHUB_PUBLIC_URL` must be the HTTPS URL: the enrollment install command shown in the
admin UI is built from it.

## Own certificates / other proxies

Any reverse proxy works: forward to `api:8000`, preserve the `X-Request-ID` header, and keep
the long-poll route `/api/v1/agents/*/operations/poll` timeout above 30 s. Agents trust the
system CA store; for a private CA set `ca_bundle` in the agent config.

## Metrics and logs

- `/metrics` is unauthenticated; keep it off the public listener (the Caddyfile does).
- Set `TARGETHUB_LOG_FORMAT=json` for one JSON object per line on stdout (each record carries
  `extra.request_id`); `TARGETHUB_LOG_DIR` relocates the rotating file log.
- Every response carries `X-Request-ID`; a client-supplied `X-Request-ID` matching
  `[A-Za-z0-9._-]{8,64}` is reused so traces can be correlated end to end.

## Verification status

The compose overlay is validated with `docker compose config`; certificate issuance was not
exercised (needs a public DNS name).
