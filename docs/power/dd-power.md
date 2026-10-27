# DD power system

TargetHub controls boards wired to a **DD (Doordarshan) power system** through the DD Endpoint Control
REST API. Calls are made **from the TargetHub server**, so a team can use reservations plus power control
with **no agents at all**.

DD switches relay *endpoints* (1 to N) on *nodes* behind a *hub* (identified by its MAC address). DD only
switches power; there is no reset line. In TargetHub:

| Operation | What happens |
| --- | --- |
| `status` | `GET /api/hubs/<mac>/nodes/<id>/endpoints/<n>`: last state reported by the device |
| `on` / `off` | `POST /api/endpoints/control` with `state` ON/OFF, then poll status until the device **confirms** |
| `cycle` | OFF (confirmed), wait `cycle_delay_seconds`, ON (confirmed) |
| `reset` | Same as `cycle` (power-cycle reset) |

DD answers `202 Accepted` when it has **published** a command, not when the relay has switched. TargetHub
therefore polls the status endpoint until `current_state` matches, up to `confirm_timeout_seconds`. If the
device does not confirm in time, the operation still succeeds but reports `confirmed: false`
("accepted; device has not confirmed yet"), so users are never told a board is off when it might not be.

## 1. Give the server the API key

The key never goes into the database or the UI. Put it in the server environment:

```bash
echo 'TARGETHUB_DD_API_KEY=<key>' >> .env
docker compose up -d        # recreates the api container with the new variable
```

Several DD servers? Use a variable per server (`TARGETHUB_DD_LAB2_KEY=…`) and reference it per capability.
TargetHub sends the key as `X-API-Key`.

## 2. Add the capability

**Admin → Targets** → edit (or add) the target → add a capability of type **Power** with backend
**DD power system (server)**, then fill in:

| Field | Example | Notes |
| --- | --- | --- |
| DD server URL | `http://dd-server:5003` | As reachable **from the TargetHub server/container** |
| Hub MAC | `AA:BB:CC:DD:EE:FF` | `:`/`-` separated or plain hex |
| Node ID | `1` | |
| Endpoint | `2` | Relay endpoint on that node |
| API key env var (on the server) | `TARGETHUB_DD_API_KEY` | Name of the environment variable, not the key |
| Cycle off-time | `3` s | Off-time during cycle/reset (0.5 to 60) |
| Confirm timeout | `10` s | How long to wait for device confirmation (0 to 120) |

The equivalent `provider_config` for the API/SDK:

```json
{"driver": "dd", "base_url": "http://dd-server:5003", "hub_mac": "AA:BB:CC:DD:EE:FF",
 "node_id": 1, "endpoint": 2, "api_key_env": "TARGETHUB_DD_API_KEY",
 "cycle_delay_seconds": 3, "confirm_timeout_seconds": 10, "timeout_seconds": 10}
```

An inline `api_key` is rejected on purpose.

Click **Test connection** in the capability editor: the server reads the endpoint status with these
settings (nothing is switched) and shows the state or the exact error. **Admin → Overview** also warns when
the API key variable is missing.

## 3. Test

Reserve the target, open a **power** session and run **Status**, then **Power on**. The result shows the
confirmed state, endpoint name and whether the node is connected.

## Errors

| DD response | What TargetHub shows | Typical fix |
| --- | --- | --- |
| 400 | DD rejected the request (check hub MAC, node ID and endpoint) | Fix the capability fields |
| 401 | DD API key is missing or was rejected | Set or rotate the env variable, `docker compose up -d` |
| 404 | DD node or endpoint not found | Wrong node/endpoint, or the node is not registered |
| 423 | DD hub is under emergency lock; power control is blocked | Clear the emergency on the DD side |
| 500 | DD failed to publish the command | DD/MQTT broker problem |
| no answer | DD unreachable | Network/firewall between server and DD; with Docker, the container must resolve and reach the DD host |

## Network notes

- With Docker, `localhost` inside the container is the container itself. Use the DD server's hostname or
  IP. For a DD server (or the mock) on the same Windows/macOS machine use `http://host.docker.internal:5003`.
- If only a lab machine can reach DD, run DD through an agent on that machine instead (fallback, see
  [agent guide](../agents/agent-guide.md#power-through-dd-from-an-agent-fallback)).

## Trying it without hardware

`tools/simulators/dd_mock_server.py` implements the DD contract (including async confirmation, emergency
lock and failures) and `tools/demo_lab.py` wires it to demo targets. See [Simulators](../development/simulators.md).

## Verification status

The driver is tested against the mock DD server built from the API reference (control, status, 202
semantics, 400/401/404/423/500, unconfirmed commands, cycle ordering). It has **not** yet run against a
real DD installation. Please run the DD section of the
[manual verification checklist](../MANUAL_VERIFICATION_CHECKLIST.md) and report any mismatch in field
names or status codes.
