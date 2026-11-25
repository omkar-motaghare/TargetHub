# Provider plugins

A plugin adds a power controller, debugger or other server-side driver to TargetHub without changing the
server's code. The capability then selects it with `"driver": "<name>"` in its provider configuration
(Admin → Targets → capability → *Custom driver* → JSON).

Plugins run **inside the server process** as ordinary code. Install only packages you trust, the same as any
Python dependency. Hardware attached to an agent host does not need a plugin: use the agent's resources.

## The contract

A plugin is an object (or a class that TargetHub instantiates) with:

```python
from app.providers.base import ProviderOperationResult, TargetProvider


class MySwitch(TargetProvider):
    capability_type = "power"

    def __init__(self, provider_key, host):
        self.provider_key, self.host = provider_key, host

    def health_check(self):
        return ProviderOperationResult(True, "reachable")

    def operations(self):                       # what the UI offers
        return ["health", "status", "on", "off", "cycle"]

    def execute(self, operation, params=None):  # runs for an authorised, owned session
        if operation == "on":
            ...                                  # talk to the device
            return ProviderOperationResult(True, "switched on", {"state": "on"})
        return super().execute(operation, params)


class MySwitchPlugin:
    name = "myswitch"                       # lower case; the value of provider_config["driver"]
    capability_types = ("power", "reset")   # capability types it serves

    def validate(self, provider_key, provider_config):
        if not provider_config.get("host"):
            raise ValueError("myswitch needs 'host'")   # shown to the admin when saving

    def build(self, provider_key, provider_config):
        return MySwitch(provider_key, provider_config["host"])
```

`validate` runs when an admin saves the capability and again before every session, so a bad configuration is
reported early. `build` runs once per session. Power results are expected to carry `data.state` (`on`/`off`)
so that the UI can show the board's state. `dd`, `http`, `simulated`, `real` and `agent` are built-in driver names
and cannot be used.

## Installing a plugin

Either publish a package with an entry point:

```toml
[project.entry-points."targethub.providers"]
myswitch = "my_package.plugin:MySwitchPlugin"
```

and `pip install` it into the server's environment (for Docker, add it to a derived image), or point the server at
a module on its `PYTHONPATH`, which is convenient for a single file mounted into the container:

```bash
TARGETHUB_PROVIDER_PLUGINS=lab_plugins:MySwitchPlugin,other_module:PLUGIN
```

Restart the server. `GET /api/v1/providers/plugins` (admin only) lists the loaded plugins and any
that failed to load; a broken plugin is logged and skipped, it never prevents the server from starting.

## Testing

Register the plugin object in a test with `app.providers.plugins.register(MySwitchPlugin())`, create a target with
`{"capability_type": "power", "provider_config": {"driver": "myswitch", "host": "..."}}` and drive a session through
the API. `tests/test_provider_plugins.py` in the repository is a complete example.
