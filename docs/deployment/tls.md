# TLS and network exposure

Agents send long-lived credentials and users send passwords, so production servers must be served over
HTTPS. Agents refuse `http://` server URLs unless `allow_insecure_http` is set (closed lab networks only).

## Caddy (automatic certificates)

```bash
scripts/install.sh --domain hub.example.com          # Linux/macOS
.\scripts\install.ps1 -Domain hub.example.com        # Windows
```

This adds `docker-compose.tls.yml`: a Caddy container on ports 80/443 with Let's Encrypt certificates
(needs a public DNS name pointing at the host), removes the API's host port, and returns 404 for `/metrics`
on the public listener. `docker/Caddyfile` sets HSTS, `nosniff` and `Referrer-Policy`. WebSockets (the serial
console) pass through without extra configuration.

`TARGETHUB_PUBLIC_URL` must be the HTTPS URL: agent install commands are built from it.

For an internal CA or a name without public DNS, replace the site block in `docker/Caddyfile` with
`tls /certs/hub.crt /certs/hub.key` and mount the files into the Caddy container.

## Your own reverse proxy

Forward to the API port (`TARGETHUB_BIND`/`TARGETHUB_PORT`, default `127.0.0.1:8000` behind a proxy) and:

- pass WebSocket upgrades for `/api/v1/sessions/*/serial/ws`;
- allow at least 60 s idle time on `/api/v1/agents/*/operations/poll` (long-poll) and the WebSocket;
- preserve or set `X-Request-ID` if you want end-to-end correlation;
- keep `/metrics` internal.

nginx example:

```nginx
location / {
    proxy_pass http://127.0.0.1:8000;
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection $connection_upgrade;   # map $http_upgrade $connection_upgrade { default upgrade; '' close; }
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_read_timeout 300s;
}
```

Agents trust the system CA store; for a private CA set `ca_bundle` in the agent config. The CLI/SDK honour
`TARGETHUB_CA_BUNDLE`.

## Metrics and logs

- `/metrics` requires `Authorization: Bearer $METRICS_TOKEN` (or an admin token). Keep it on the internal network.
- `TARGETHUB_LOG_FORMAT=json` emits one JSON object per line on stdout (each record carries `extra.request_id`).
- Every response carries `X-Request-ID`; a client-supplied value matching `[A-Za-z0-9._-]{8,64}` is reused.

## Verification status

The compose overlay is validated with `docker compose config`. Certificate issuance needs a public DNS
name and was not exercised in development.
