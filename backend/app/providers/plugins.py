"""Third-party provider plugins: add a power controller, debugger or other driver without forking.

A plugin is a Python object (usually a small class instance) with these attributes::

    name = "tasmota"                       # the value of provider_config["driver"]
    capability_types = ("power", "reset")  # capability types it can serve

    def validate(self, provider_key: str, provider_config: dict) -> None:
        '''Raise ValueError with a clear message when the configuration is unusable.'''

    def build(self, provider_key: str, provider_config: dict) -> TargetProvider:
        '''Return a provider; it runs on the server for the session.'''

Plugins are found in two ways. Packages register an entry point in the ``targethub.providers`` group
(a ``module:attribute`` pointing at the plugin object), or an operator lists ``module:attribute`` specs in the
``TARGETHUB_PROVIDER_PLUGINS`` environment variable (comma separated) for modules on ``PYTHONPATH``.
A capability then selects it with ``"driver": "<name>"`` in its provider configuration.

Plugins are ordinary code that runs inside the server: install only packages you trust. A plugin that fails
to load or is malformed is logged and skipped; it never stops the server from starting.
"""

from __future__ import annotations

import importlib
import os
import threading
from dataclasses import dataclass, field
from importlib import metadata
from typing import Any

from app.core.logging import logger
from app.providers.base import TargetProvider

ENTRY_POINT_GROUP = "targethub.providers"
ENV_VAR = "TARGETHUB_PROVIDER_PLUGINS"


@dataclass
class PluginInfo:
    name: str
    capability_types: tuple[str, ...]
    source: str
    plugin: Any = field(repr=False, default=None)


_lock = threading.Lock()
_plugins: dict[str, PluginInfo] = {}
_errors: list[str] = []
_loaded = False


def _check(plugin: Any) -> tuple[str, tuple[str, ...]]:
    name = getattr(plugin, "name", None)
    types = getattr(plugin, "capability_types", None)
    if not isinstance(name, str) or not name.strip() or name != name.strip().lower() or " " in name:
        raise ValueError("plugin 'name' must be a lower-case string without spaces")
    if not isinstance(types, (tuple, list)) or not types or not all(isinstance(item, str) for item in types):
        raise ValueError("plugin 'capability_types' must be a non-empty tuple of capability type names")
    for method in ("validate", "build"):
        if not callable(getattr(plugin, method, None)):
            raise ValueError(f"plugin needs a '{method}' method")
    return name, tuple(types)


def register(plugin: Any, source: str = "code") -> PluginInfo:
    """Register a plugin object (raises ValueError when it does not follow the contract)."""
    from app.providers import registry

    name, types = _check(plugin)
    unknown = [item for item in types if item not in registry.CAPABILITY_PROVIDERS]
    if unknown:
        raise ValueError(f"unknown capability type(s): {', '.join(unknown)}")
    reserved = {"dd", "http", "simulated", "real", "agent"}
    if name in reserved:
        raise ValueError(f"'{name}' is a built-in driver name")
    info = PluginInfo(name=name, capability_types=types, source=source, plugin=plugin)
    with _lock:
        if name in _plugins:
            raise ValueError(f"a plugin named '{name}' is already registered ({_plugins[name].source})")
        _plugins[name] = info
    return info


def _import_spec(spec: str) -> Any:
    module_name, _, attribute = spec.partition(":")
    if not module_name or not attribute:
        raise ValueError(f"'{spec}' must look like 'package.module:attribute'")
    value = getattr(importlib.import_module(module_name), attribute)
    return value() if isinstance(value, type) else value


def load() -> None:
    """Discover plugins once per process."""
    global _loaded
    with _lock:
        if _loaded:
            return
        _loaded = True
    candidates: list[tuple[str, Any]] = []
    try:
        for entry in metadata.entry_points(group=ENTRY_POINT_GROUP):
            candidates.append((f"entry point {entry.name}", entry))
    except Exception as exc:  # noqa: BLE001
        _errors.append(f"could not list entry points: {exc}")
    for spec in filter(None, (part.strip() for part in os.getenv(ENV_VAR, "").split(","))):
        candidates.append((f"{ENV_VAR} {spec}", spec))
    for source, item in candidates:
        try:
            if isinstance(item, str):
                plugin = _import_spec(item)
            else:
                value = item.load()
                plugin = value() if isinstance(value, type) else value
            info = register(plugin, source)
            logger.info(f"Loaded provider plugin '{info.name}' for {', '.join(info.capability_types)} ({source})")
        except Exception as exc:  # noqa: BLE001 - a bad plugin must not break the server
            _errors.append(f"{source}: {exc}")
            logger.warning(f"Skipping provider plugin from {source}: {exc}")


def find(capability_type: str, driver: str | None) -> PluginInfo | None:
    """The plugin selected by ``driver`` for this capability type, if any."""
    if not driver:
        return None
    load()
    with _lock:
        info = _plugins.get(str(driver).strip().lower())
    if info is not None and capability_type in info.capability_types:
        return info
    return None


def build(info: PluginInfo, provider_key: str, provider_config: dict[str, Any]) -> TargetProvider:
    provider = info.plugin.build(provider_key, provider_config)
    if not isinstance(provider, TargetProvider):
        raise ValueError(f"plugin '{info.name}' did not return a TargetProvider")
    return provider


def describe() -> dict[str, Any]:
    load()
    with _lock:
        loaded = [
            {"name": item.name, "capability_types": list(item.capability_types), "source": item.source}
            for item in sorted(_plugins.values(), key=lambda value: value.name)
        ]
        return {"plugins": loaded, "errors": list(_errors)}


def reset_for_tests() -> None:
    global _loaded
    with _lock:
        _plugins.clear()
        _errors.clear()
        _loaded = False
