"""Holds the plugin registry and connector instances built at startup
(v0.9, Phase 102) - a separate module from `app/main.py` purely to avoid
a circular import: `main.py` includes `app/api/plugins.py`'s router,
and that router needs to read this same state, so the state can't live
on `main` itself without `api/plugins.py` importing back into it.

Both start out empty/unpopulated, never `None` - anything reading these
before `main.py`'s lifespan runs sees an honest "nothing yet" (an empty
registry, an empty connector dict) rather than an AttributeError, same
convention `main.py`'s own pre-Phase-102 `plugin_registry` global
already established.
"""
from __future__ import annotations

from app.plugins.connector_instance import ConnectorInstance
from app.plugins.registry import PluginRegistry

plugin_registry: PluginRegistry = PluginRegistry()
connector_instances: dict[str, ConnectorInstance] = {}
