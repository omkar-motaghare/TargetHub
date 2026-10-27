# CLI, Python SDK and CI / hardware-in-the-loop

Everything in the UI is available over the REST API (`/docs` on your server has the OpenAPI reference).
The Python SDK wraps it, and the `targethub` CLI wraps the SDK. The CLI prints JSON, which is easy to
use from shell scripts and CI.

## Install

```bash
pip install "targethub-sdk[console] @ git+https://github.com/omkar-motaghare/TargetHub#subdirectory=sdk/python"
# or the wheel attached to a GitHub release:  pip install targethub_sdk-0.2.0-py3-none-any.whl
```

Python 3.10+. The `console` extra adds `websockets` for `targethub console`.

## Authentication for automation

Create a **personal API token** (Account → API tokens, or `targethub token create ci-nightly --expires-days 90`)
for a dedicated user such as `ci-bot` with role *user*. Store it as a CI secret and pass:

```bash
export TARGETHUB_URL=https://hub.example.com
export TARGETHUB_TOKEN=thp_...
# private CA: export TARGETHUB_CA_BUNDLE=/path/ca.pem
```

## CLI reference

```text
targethub whoami | targets [--tag T] [--free] | reservations | calendar | waitlist | sessions
targethub reserve <target> | --tag T  [--minutes N] [--note TEXT] [--wait --timeout S]
targethub extend <reservation-id> --minutes N
targethub release <reservation-id | target>
targethub open <reservation-id> <serial|power|deploy> [--capability-id ID]
targethub power <session-id> <status|on|off|cycle|reset>
targethub serial <session-id> [--send TEXT] [--expect TEXT] [--wait SECONDS]
targethub console <session-id>                     # interactive, Ctrl+] to quit
targethub log <session-id> [--include-input]        # transcript
targethub deploy <session-id> <url> <sha256> [--no-wait] [--timeout S]
targethub close <session-id>
targethub token create NAME [--expires-days N] | token list | token revoke ID
```

`reserve --wait` joins the waitlist when the board (or every board with the tag) is busy and blocks until
TargetHub grants the reservation, so CI jobs queue fairly with humans.

## Example: GitHub Actions on a self-hosted runner

```yaml
jobs:
  hil:
    runs-on: [self-hosted, lab]
    env:
      TARGETHUB_URL: https://hub.example.com
      TARGETHUB_TOKEN: ${{ secrets.TARGETHUB_TOKEN }}
    steps:
      - uses: actions/checkout@v4
      - run: pip install "targethub-sdk @ git+https://github.com/omkar-motaghare/TargetHub#subdirectory=sdk/python"
      - name: Build firmware
        run: make firmware.bin && sha256sum firmware.bin | cut -d' ' -f1 > firmware.sha256
      - name: Publish artifact where the agent can download it
        run: ./scripts/upload-artifact.sh firmware.bin   # any HTTPS location the agent can reach
      - name: Hardware test
        run: |
          set -euo pipefail
          res=$(targethub reserve --tag stm32 --minutes 30 --note "CI ${GITHUB_RUN_ID}" --wait --timeout 1800 | jq -r .id)
          trap 'targethub release "$res" >/dev/null' EXIT
          power=$(targethub open "$res" power | jq -r .id)
          deploy=$(targethub open "$res" deploy | jq -r .id)
          serial=$(targethub open "$res" serial | jq -r .id)
          targethub deploy "$deploy" "$ARTIFACT_URL" "$(cat firmware.sha256)"
          targethub power "$power" cycle
          targethub serial "$serial" --expect "Self-test PASSED" --wait 60
          targethub log "$serial" > serial.log
      - uses: actions/upload-artifact@v4
        if: always()
        with: { name: serial-log, path: serial.log }
```

The same steps work in GitLab CI, Jenkins or Azure Pipelines; only the secret handling differs.

## Example: Python SDK (pytest fixture)

```python
import os
import pytest
from targethub_sdk import TargetHubClient


@pytest.fixture
def board():
    with TargetHubClient(os.environ["TARGETHUB_URL"], token=os.environ["TARGETHUB_TOKEN"]) as hub:
        reservation = hub.wait_for_reservation(tag="stm32", minutes=30, timeout=1800, note="pytest HIL")
        try:
            serial = hub.open_session(reservation["id"], "serial")
            power = hub.open_session(reservation["id"], "power")
            hub.serial_open(serial["id"])
            yield hub, serial["id"], power["id"]
        finally:
            hub.release_reservation(reservation["id"])


def test_boots_after_power_cycle(board):
    hub, serial, power = board
    hub.power(power, "cycle")          # raises TargetHubError if the operation fails
    banner = hub.serial_expect(serial, "board>", timeout=30)
    assert "Firmware" in banner
```

Useful SDK calls: `list_targets(tag)`, `reserve(target, minutes)`, `reserve_any(tag, minutes)`,
`wait_for_reservation(...)`, `extend_reservation(id, minutes)`, `open_session(reservation_id, type)`,
`serial_write`, `serial_read(size, wait_ms)`, `serial_expect(pattern, timeout)`, `serial_log`,
`power(session, op)`, `deploy(session, url, sha256)`, `submit()`/`wait_operation()` for async
operations, `notifications()`. Errors raise `TargetHubError(status_code, detail)`.

## Tips

- Always release in a `finally`/`trap`. If a job is killed anyway, the reservation expires at its end time.
- Give CI its own tag (`ci-pool`) and boards, or let CI join the waitlist like everyone else.
- Keep CI tokens short-lived and per pipeline; revoke them from Account → API tokens.
- Webhooks (`reservation.*`) let chat channels see what CI is holding.
