# Simulators and the demo lab

Everything in TargetHub can be exercised without hardware. That is useful for evaluating it, training a
team, developing, and CI.

| Tool | What it simulates | Platforms |
| --- | --- | --- |
| `tools/simulators/dd_mock_server.py` | The DD Endpoint Control API: control/status, 202 + delayed confirmation, API key, 400/401/404/423/500 | Windows, Linux, macOS |
| `tools/simulators/virtual_board.py` | A board on a pseudo-terminal: boot log, `board>` prompt, `help`/`version`/`uptime`/`echo`/`reboot`; follows a DD endpoint so it boots when powered on | Linux, macOS, Raspberry Pi |
| Agent `sim://…` resources | A built-in virtual board inside the agent (echoing console) | all, including Windows |
| `tools/demo_lab.py` | Starts the DD mock, the virtual board and a local agent; creates demo targets | all |
| `tools/verify_demo_lab.py` | End-to-end check of a running demo lab | all |

Only standard-library Python is needed for the simulators and the demo lab. `verify_demo_lab.py` needs
`httpx` and `websockets` (both in the backend virtualenv).

## The demo lab in five minutes

1. Start a server. The DD mock uses the key `demo-dd-key`, so give the server that key:

   ```bash
   # Docker: add to .env, then docker compose up -d
   TARGETHUB_DD_API_KEY=demo-dd-key
   # or a dev server: export TARGETHUB_DD_API_KEY=demo-dd-key before starting uvicorn
   ```

2. Run the demo lab on any machine that can reach the server:

   ```bash
   python tools/demo_lab.py --hub http://localhost:8000 --admin admin --password '<admin password>'
   # fresh server without users: add --bootstrap-token <ADMIN_BOOTSTRAP_TOKEN>
   # server in Docker on this machine: add --dd-url-for-hub http://host.docker.internal:5003
   #   (Linux Docker: use the host's LAN IP, or run the server with --add-host)
   ```

3. Open the UI. You get:
   - **DEMO-BOARD-01**: serial console through the agent and DD power from the server. Power it on and
     watch it boot; power-cycle it and watch it reboot.
   - **DEMO-POWER-02**: DD power only, no agent involved (the "power + reservations" team setup).

4. Optionally verify everything automatically:

   ```bash
   backend/.venv/bin/python tools/verify_demo_lab.py --hub http://localhost:8000 --admin admin --password '…'
   ```

   It reserves the board, powers it on through DD, waits for the boot banner on the WebSocket console,
   runs a command, power-resets, checks the reboot and the stored transcript. Exit code 0 means all steps
   passed.

Ctrl+C stops the simulators and the agent. Logs are under the temp directory printed at start.

No simulated providers are involved: the server runs real DD and agent code paths, so this works with
`ENVIRONMENT=production` and `ALLOW_SIMULATED_PROVIDERS` unset.

## DD mock controls

```bash
python tools/simulators/dd_mock_server.py --port 5003 --hub-mac AA:BB:CC:DD:EE:FF --api-key demo-dd-key \
  --nodes 2 --endpoints 10 --confirm-delay 0.7
curl -X POST 'http://localhost:5003/_mock/emergency?active=1'     # 423 on control
curl -X POST 'http://localhost:5003/_mock/fail-next?status=500'   # next control fails
curl -X POST 'http://localhost:5003/_mock/disconnect?node_id=1'   # device stops confirming
curl http://localhost:5003/_mock/state                            # every endpoint
```

## Virtual serial on Windows

Use `sim://` resources in the agent config:

```json
{"resource_key": "sim://board-1", "resource_type": "serial", "display_name": "Simulated board",
 "metadata": {"simulated": true}}
```

For a real COM-port pair, install a virtual null-modem driver such as com0com and point a terminal
emulator or script at the other end.

## Simulated providers on the server

Separate from the tools above, the server has simulated power/serial/deploy providers for quick UI demos.
They are **disabled by default outside development**, so a misconfigured production target cannot
silently fake power. Enable them only on demo instances with `ALLOW_SIMULATED_PROVIDERS=true`.
