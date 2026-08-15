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

from typing import Any

from app.plugins.connector_instance import ConnectorInstance
from app.plugins.poll_runner import PollRunner
from app.plugins.registry import PluginRegistry
from app.plugins.resource_collector_instance import ResourceCollectorInstance

plugin_registry: PluginRegistry = PluginRegistry()
connector_instances: dict[str, ConnectorInstance] = {}
# {connector_id: (PredictionConnectorInstance|GroundTruthConnectorInstance,
# PollRunner)} - v0.9 bug hunt, issue #110. Kept here (not just the
# runner) so shutdown can stop the connector itself, not only its
# polling thread.
poll_runners: dict[str, tuple[Any, PollRunner]] = {}

# {collector_id: (ResourceCollectorInstance, static_config, poll_interval_s)}
# - v0.9.1, issue #111. Built once at boot from `resource_collectors:`
# config (app/plugins/manager.py's build_resource_collector_instances()),
# but never configured/started here - a resource collector is
# session-bound, not process-bound (unlike poll_runners above). Held so
# api/sessions.py's start_session/complete_session can find them.
resource_collectors: dict[str, tuple[ResourceCollectorInstance, dict, float]] = {}

# {session_id: {collector_id: (ResourceCollectorInstance, PollRunner)}} -
# populated by start_session, consumed and cleared by complete_session,
# and drained (all sessions) at shutdown. A session_id key only exists
# here while that session is actively being live-collected.
resource_collection_runners: dict[str, dict[str, tuple[ResourceCollectorInstance, PollRunner]]] = {}
