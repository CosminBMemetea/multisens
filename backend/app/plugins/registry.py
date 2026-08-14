"""Plugin discovery and the `PluginRegistry` (v0.9, Phase 94).

Discovery only ever inspects explicitly declared `multisens.plugins`
entry points (`importlib.metadata.entry_points(group=ENTRY_POINT_GROUP)`)
- never a directory scan, never a blind module import (docs/plugin-sdk.md,
"Discovery: Python entry points, not directory scanning").

## Entry point name == plugin_id, always

The registered entry-point *name* must equal the plugin's own
`descriptor().plugin_id` - this is a required convention, not a
coincidence. It's what lets the `plugins.disabled` config list work
*before* a disabled plugin's code is ever imported (real safety benefit,
not just bookkeeping) and lets duplicate-id detection work off entry
point metadata alone, without instantiating anything. A mismatch between
the two is treated as a plugin-author error - `LOAD_FAILED`, never
silently using one name over the other.

## Two status axes, never conflated

`PluginStatus` (this module) is installation-level - computed once when
the registry is built, describing whether a plugin's own code could be
loaded and is compatible at all. It says nothing about whether a
connector instance is currently running - that's `ConnectorState`
(`multisens_sdk.plugin`), tracked separately starting Phase 95.

## Failure isolation

Every step that touches plugin-provided code (`entry_point.load()`,
calling the loaded factory, calling `.descriptor()`) is wrapped
individually - one plugin's exception is recorded on its own
`PluginRecord` and never stops discovery of the next entry point, and
never escapes `discover_plugins()` itself. What this can't catch (a
segfault, a thread the plugin spawns and never joins, a genuinely
malicious action taken with the process's own permissions) is documented
honestly in docs/plugin-sdk.md, not hidden.
"""
from __future__ import annotations

import importlib.metadata
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Iterable

from multisens_sdk import MULTISENS_PLUGIN_API_VERSION, PluginDescriptor

ENTRY_POINT_GROUP = 'multisens.plugins'


class PluginStatus(str, Enum):
    AVAILABLE = 'available'
    INCOMPATIBLE = 'incompatible'
    LOAD_FAILED = 'load_failed'
    DISABLED = 'disabled'


@dataclass
class PluginRecord:
    """One installed plugin's registry entry. `descriptor` is `None` only
    when it couldn't be obtained at all (import failure, a `descriptor()`
    call that itself raised, or a duplicate rejected before load was even
    attempted). `instance` is set **only** for `AVAILABLE` plugins - an
    `INCOMPATIBLE`/`LOAD_FAILED`/`DISABLED` plugin's runtime methods
    (`start`/`evaluate`/...) are never called, so there is nothing to
    keep an instance around for."""
    plugin_id: str
    status: PluginStatus
    descriptor: PluginDescriptor | None
    instance: Any | None
    error: str | None = None
    distribution_name: str | None = None
    distribution_version: str | None = None


@dataclass
class PluginRegistry:
    records: dict[str, PluginRecord] = field(default_factory=dict)

    def available(self) -> list[PluginRecord]:
        return [r for r in self.records.values() if r.status == PluginStatus.AVAILABLE]

    def get(self, plugin_id: str) -> PluginRecord | None:
        return self.records.get(plugin_id)


def _register(registry: PluginRegistry, record: PluginRecord) -> None:
    registry.records[record.plugin_id] = record
    if record.status != PluginStatus.AVAILABLE:
        # print(), not the logging module - this project has no logging
        # subsystem anywhere else (backend/app has zero prior `logging`
        # usage); print() is the established convention for exactly this
        # kind of operator-visible startup diagnostic, same as
        # ros2_ws's own sensor_config.py "skipping sensor ..." messages.
        suffix = f' - {record.error}' if record.error else ''
        print(f'plugin {record.plugin_id}: {record.status.value}{suffix}')


def register_built_in(registry: PluginRegistry, instance: Any, *, source: str = 'multisens') -> None:
    """Built-in plugins (the three v0.8 evaluators, `multisens.builtin.
    sensor.rtsp` from Phase 96 onward) are directly imported by backend
    code, never routed through entry-point discovery - there is no
    package to discover, the code already lives in this repository. They
    go through the exact same duplicate/compatibility checks as an
    external plugin, never a privileged fast path."""
    try:
        descriptor = instance.descriptor()
    except Exception as e:  # noqa: BLE001 - a plugin's own code, must never crash the registry
        _register(registry, PluginRecord(
            plugin_id=f'<unknown:{source}>', status=PluginStatus.LOAD_FAILED,
            descriptor=None, instance=None, error=str(e), distribution_name=source,
        ))
        return

    if descriptor.plugin_id in registry.records:
        existing = registry.records[descriptor.plugin_id]
        msg = (
            f"duplicate plugin_id '{descriptor.plugin_id}': already registered from "
            f"{existing.distribution_name}, also found in {source} - neither is used"
        )
        _register(registry, PluginRecord(
            plugin_id=descriptor.plugin_id, status=PluginStatus.LOAD_FAILED,
            descriptor=None, instance=None, error=msg, distribution_name=source,
        ))
        existing.status = PluginStatus.LOAD_FAILED
        existing.instance = None
        existing.error = msg
        return

    if descriptor.api_version != MULTISENS_PLUGIN_API_VERSION:
        _register(registry, PluginRecord(
            plugin_id=descriptor.plugin_id, status=PluginStatus.INCOMPATIBLE,
            descriptor=descriptor, instance=None,
            error=(f"plugin requires API '{descriptor.api_version}', "
                   f"MultiSens provides '{MULTISENS_PLUGIN_API_VERSION}'"),
            distribution_name=source,
        ))
        return

    _register(registry, PluginRecord(
        plugin_id=descriptor.plugin_id, status=PluginStatus.AVAILABLE,
        descriptor=descriptor, instance=instance, error=None, distribution_name=source,
    ))


def _discover_one(registry: PluginRegistry, entry_point: Any, disabled_plugin_ids: set[str]) -> None:
    plugin_id = entry_point.name
    dist = getattr(entry_point, 'dist', None)
    distribution_name = getattr(dist, 'name', None)
    distribution_version = getattr(dist, 'version', None)

    if plugin_id in registry.records:
        existing = registry.records[plugin_id]
        msg = (
            f"duplicate plugin_id '{plugin_id}': already registered from "
            f"{existing.distribution_name}, also found in {distribution_name or 'unknown distribution'} - "
            f"neither is used"
        )
        _register(registry, PluginRecord(
            plugin_id=plugin_id, status=PluginStatus.LOAD_FAILED, descriptor=None, instance=None,
            error=msg, distribution_name=distribution_name, distribution_version=distribution_version,
        ))
        existing.status = PluginStatus.LOAD_FAILED
        existing.instance = None
        existing.error = msg
        return

    # Checked BEFORE loading - a disabled plugin's code is never imported
    # or executed at all, a real safety property, not just bookkeeping.
    if plugin_id in disabled_plugin_ids:
        _register(registry, PluginRecord(
            plugin_id=plugin_id, status=PluginStatus.DISABLED, descriptor=None, instance=None,
            error=None, distribution_name=distribution_name, distribution_version=distribution_version,
        ))
        return

    try:
        factory = entry_point.load()
        instance = factory() if callable(factory) else factory
        descriptor = instance.descriptor()
    except Exception as e:  # noqa: BLE001 - untrusted plugin code, must never crash discovery
        _register(registry, PluginRecord(
            plugin_id=plugin_id, status=PluginStatus.LOAD_FAILED, descriptor=None, instance=None,
            error=str(e), distribution_name=distribution_name, distribution_version=distribution_version,
        ))
        return

    if descriptor.plugin_id != plugin_id:
        msg = (
            f"entry point name '{plugin_id}' does not match descriptor.plugin_id "
            f"'{descriptor.plugin_id}' - both must agree"
        )
        _register(registry, PluginRecord(
            plugin_id=plugin_id, status=PluginStatus.LOAD_FAILED, descriptor=descriptor, instance=None,
            error=msg, distribution_name=distribution_name, distribution_version=distribution_version,
        ))
        return

    if descriptor.api_version != MULTISENS_PLUGIN_API_VERSION:
        _register(registry, PluginRecord(
            plugin_id=plugin_id, status=PluginStatus.INCOMPATIBLE, descriptor=descriptor, instance=None,
            error=(f"plugin requires API '{descriptor.api_version}', "
                   f"MultiSens provides '{MULTISENS_PLUGIN_API_VERSION}'"),
            distribution_name=distribution_name, distribution_version=distribution_version,
        ))
        return

    _register(registry, PluginRecord(
        plugin_id=plugin_id, status=PluginStatus.AVAILABLE, descriptor=descriptor, instance=instance,
        error=None, distribution_name=distribution_name, distribution_version=distribution_version,
    ))


def discover_plugins(
    *, disabled_plugin_ids: Iterable[str] = (), entry_points: Iterable[Any] | None = None,
    ros_bridge: Any = None,
) -> PluginRegistry:
    """Builds a fresh `PluginRegistry`. Built-in evaluators (and, if
    `ros_bridge` is supplied, the built-in RTSP `SensorConnector` - Phase
    96) register first (directly, not via entry points); external
    plugins are discovered from `multisens.plugins` entry points second,
    so a built-in and an external plugin colliding on the same
    `plugin_id` goes through the identical duplicate-rejection path
    either way.

    `entry_points` is injectable purely for testing (a list of
    entry-point-like objects with `.name`/`.load()`/optionally `.dist`) -
    `None` (the default) calls the real
    `importlib.metadata.entry_points(group=ENTRY_POINT_GROUP)`.
    `ros_bridge` is `None` by default (most tests have no real
    `RosBridge` and don't need the RTSP connector registered at all);
    `app/main.py` passes its own real bridge instance.
    """
    from app.domain.evaluators import EVALUATOR_REGISTRY
    from app.plugins.builtin_rtsp import RtspSensorConnector

    registry = PluginRegistry()
    disabled = set(disabled_plugin_ids)

    for evaluator in EVALUATOR_REGISTRY.values():
        register_built_in(registry, evaluator, source='multisens')
    if ros_bridge is not None:
        register_built_in(registry, RtspSensorConnector(ros_bridge), source='multisens')

    resolved_entry_points = (
        entry_points if entry_points is not None
        else importlib.metadata.entry_points(group=ENTRY_POINT_GROUP)
    )
    for entry_point in resolved_entry_points:
        _discover_one(registry, entry_point, disabled)

    return registry
