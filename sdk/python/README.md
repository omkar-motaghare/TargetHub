# targethub-sdk

Python client and `targethub` command line tool for the TargetHub REST API. Depends only on `httpx`.

```bash
pip install ./sdk/python            # or the built wheel: pip wheel ./sdk/python -w dist
```

## SDK

```python
from targethub_sdk import TargetHubClient

with TargetHubClient("https://hub.example.com") as hub:
    hub.login("alice", "...")
    target = hub.list_targets()[0]
    reservation = hub.create_reservation(target["id"], "2030-01-01T10:00:00Z", "2030-01-01T11:00:00Z")
    session = hub.open_session(reservation["id"], "power")
    print(hub.power(session["id"], "cycle"))
    hub.close_session(session["id"])
    hub.release_reservation(reservation["id"])
```

Errors raise `TargetHubError` (`status_code`, `detail`; status `0` means the hub was unreachable).

## CLI

```bash
export TARGETHUB_URL=https://hub.example.com
targethub login --username alice          # prompts; token saved to ~/.config/targethub/token (0600)
targethub targets
targethub reserve <target-id> --minutes 60
targethub open <reservation-id> serial
targethub serial <session-id> --send "help" --wait 3
targethub power <session-id> cycle
targethub deploy <session-id> https://host/fw.bin <sha256>
targethub close <session-id> && targethub release <reservation-id>
targethub audit --action session.open     # admin
```

`TARGETHUB_TOKEN` overrides the stored token; `--ca-bundle` / `TARGETHUB_CA_BUNDLE` trusts a private CA.
Output is JSON, except `serial`, which prints the received text. Exit status is non-zero on API errors.

## Tests

```bash
cd sdk/python && python -m venv .venv && .venv/bin/pip install -e ".[test]" && .venv/bin/pytest
```

The live hub E2E (`scripts/e2e-agent.sh`) also drives a real hub through this SDK and CLI.
