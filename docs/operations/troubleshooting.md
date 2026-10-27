# Troubleshooting

Start with `docker compose ps` and `docker compose logs --tail=200 api`. Every API response carries an
`X-Request-ID` header; search the logs for it to find the matching server-side lines.

## Server

| Symptom | Cause and fix |
| --- | --- |
| `install.sh` stops with "stack did not become healthy" | Read the printed logs. Common: port already in use (`--port`), weak or missing `SECRET_KEY` (the server refuses short or placeholder keys), database password changed after the volume was created (put the original `POSTGRES_PASSWORD` back). |
| Image pull fails with 403 / TLS errors | A corporate proxy blocks Docker Hub or GHCR. Configure Docker's proxy and registry mirror, or build on a machine with access and `docker save` / `docker load` the images. |
| UI shows "TargetHub API is running … web UI has not been built" | You run the API from source without building the frontend. See [Installation](../getting-started/install.md#running-without-docker-evaluation-or-development). |
| Everyone is logged out after a restart | `SECRET_KEY` changed. Keep `.env` stable and back it up. |
| "Too many failed attempts" on login | Rate limit after repeated failures per IP; wait `AUTH_FAILURE_WINDOW_SECONDS` (default 5 min). |
| Lost admin password | `scripts/reset_admin_user.sh reset <user>` ([Administration](../admin-guide/administration.md#recovering-access)). |
| Times look wrong | Server and clients show UTC internally and local time in the browser. Check the host clock (`timedatectl`, Windows time sync). |

## Agents

| Symptom | Cause and fix |
| --- | --- |
| Agent never appears | Look at the agent log (Linux `journalctl -u 'targethub-agent@*'`, Windows `C:\ProgramData\TargetHub\agent\*.log`). The enrollment token may have expired (30 min) or been used: create a new enrollment. |
| `certificate verify failed` | The server uses a private CA: set `ca_bundle` in the agent config. Do not switch to http. |
| "targethub_url must be https://" | Use HTTPS, or (closed lab only) set `"allow_insecure_http": true` in the agent config / re-run the installer with `--allow-insecure-http` / `-AllowInsecureHttp`. |
| Agent goes offline every few minutes | Network or proxy drops long requests. Allow ≥ 30 s idle on the path to `/api/v1/agents/*/operations/poll`; check the host is not sleeping (Windows power plan). |
| Serial port missing from resources | Check `ls -l /dev/serial/by-id/` (Linux) or Device Manager (Windows). The service user needs `dialout` membership (installer adds it; restart after adding). On Windows make sure `pyserial` is installed for the Python the task uses. |
| "Serial path … is not allowed on this Agent" | Only discovered or configured ports can be opened. Add the port to `resources` in the agent config. |
| Port busy / permission denied | Another program (screen, minicom, an IDE serial monitor) holds the port. Close it. |
| Garbage on the console | Wrong `baudrate` in the agent config for that port. |
| GPIO power fails | `gpioinfo` to confirm chip/line; user in `gpio` group; `"backend": "gpiod"` on current kernels. |
| Deploy "sha256 mismatch" | The artifact changed or the URL redirects to an error page. Recompute the hash of the exact file. |

## Power (DD and HTTP)

| Symptom | Cause and fix |
| --- | --- |
| "DD unreachable" | From the server container: `docker compose exec api python -c "import urllib.request;print(urllib.request.urlopen('http://dd-server:5003/api/hubs/<mac>/nodes/1/endpoints/1', timeout=5).status)"`. Fix DNS/routing/firewall; inside Docker `localhost` is the container. |
| "DD API key is missing or was rejected" | The variable named in `api_key_env` is not set in `.env`, or the key is wrong. Then `docker compose up -d`. |
| "accepted; device has not confirmed yet" | DD published the command but the node did not report back in `confirm_timeout_seconds`. Check the node is connected in DD; increase the timeout for slow relays. |
| "emergency lock" (423) | Clear the emergency on the DD system. TargetHub never overrides it. |
| "simulated mode, which is disabled on this server" | The capability has no real backend. Configure DD/HTTP/agent, or set `ALLOW_SIMULATED_PROVIDERS=true` on demo servers only. |

## Console

| Symptom | Cause and fix |
| --- | --- |
| Console says "Reconnecting…" forever | A proxy in front of TargetHub does not pass WebSockets. Enable WebSocket upgrade for `/api/v1/sessions/*/serial/ws` (Caddy and most proxies do by default; nginx needs `proxy_set_header Upgrade` / `Connection`). |
| "bytes of output were dropped" | The board printed more than 1 MiB while nobody was reading. The transcript keeps what was received. |
| Session closed unexpectedly | The reservation ended or an admin force-released it. Check notifications and extend earlier. |

## Getting help

Collect: server version (footer of the UI), `docker compose logs api` around the time, the agent log, the
`X-Request-ID` of the failing request, and the target/capability configuration (without secrets).
