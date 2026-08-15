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

from multisens_sdk import MULTISENS_PLUGIN_API_VERSION, PluginDescriptor, PluginType

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
    keep an instance around for.

    `factory` (v0.9, Phase 102) is a zero-arg callable that produces a
    *fresh* plugin instance - needed because `instance` above is a
    single, already-constructed object, but a connector-shaped plugin
    (`SensorConnector`/etc.) needs its own separate object per sensor id
    (`ridesafe_front_rgb`/`ridesafe_rear_rgb` sharing one connector
    *implementation* must never share one connector *object* - see
    `connector_instance.py`'s own module docstring). `None` only for the
    rare case a plugin's own factory couldn't be captured (never for a
    normally-discovered plugin)."""
    plugin_id: str
    status: PluginStatus
    descriptor: PluginDescriptor | None
    instance: Any | None
    factory: Any | None = None
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


def register_built_in(
    registry: PluginRegistry, instance: Any, *, source: str = 'multisens', factory: Any = None,
) -> None:
    """Built-in plugins (the three v0.8 evaluators, `multisens.builtin.
    sensor.rtsp` from Phase 96 onward) are directly imported by backend
    code, never routed through entry-point discovery - there is no
    package to discover, the code already lives in this repository. They
    go through the exact same duplicate/compatibility checks as an
    external plugin, never a privileged fast path.

    `factory` defaults to reusing the already-constructed `instance`
    (fine for the stateless v0.8 evaluators, which have always been
    shared this way). A caller that needs a fresh object per use - the
    RTSP connector, one object per sensor_id - passes its own zero-arg
    `factory` explicitly (see `discover_plugins()` below)."""
    factory = factory if factory is not None else (lambda inst=instance: inst)
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
        descriptor=descriptor, instance=instance, factory=factory, error=None, distribution_name=source,
    ))


def _rollback_registration_side_effects(existing: PluginRecord, registry: PluginRegistry) -> None:
    """Undoes exactly what `_discover_one`'s own `register_evaluator`/
    `register_resource_metrics` calls did for `existing`, the moment a
    later duplicate `plugin_id` invalidates it (v0.9 bug hunt, issue
    #117). Without this, the registry reports `existing` LOAD_FAILED -
    its own error message says "neither is used" - while
    `EVALUATOR_REGISTRY`/`SUPPORTED_RESOURCE_METRICS` (separate global
    namespaces `register_evaluator`/`register_resource_metrics` already
    mutated before the collision was detected) keep it fully live and
    dispatchable through `/api/evaluation` or advertised through
    `/api/resource-metrics`.

    Never applied to a built-in: `register_built_in` never calls either
    registration hook - the three built-in evaluators are the
    `EVALUATOR_REGISTRY` dict's own permanent initial contents, not
    plugin-registered - but a built-in's `instance` IS the exact same
    object already sitting in `EVALUATOR_REGISTRY` (shared by identity),
    so the identity check below would otherwise match it too and delete
    a permanent entry. `distribution_name == 'multisens'` is
    `register_built_in`'s own hard-coded default `source` (see
    `discover_plugins`) - the same signal already used to identify a
    built-in throughout this module."""
    if (existing.status != PluginStatus.AVAILABLE or existing.descriptor is None or existing.instance is None
            or existing.distribution_name == 'multisens'):
        return

    if existing.descriptor.plugin_type == PluginType.EVALUATOR:
        from app.domain.evaluators import EVALUATOR_REGISTRY
        evaluator_type = getattr(existing.instance, 'evaluator_type', None)
        # Identity check, not just key presence: evaluator_type is an
        # exclusive namespace (register_evaluator itself rejects a
        # second plugin reusing one), so if the key still points at
        # this exact instance, it is unambiguously safe to remove.
        if evaluator_type is not None and EVALUATOR_REGISTRY.get(evaluator_type) is existing.instance:
            del EVALUATOR_REGISTRY[evaluator_type]

    elif existing.descriptor.plugin_type == PluginType.RESOURCE_COLLECTOR:
        from app.domain.resources import BUILT_IN_RESOURCE_METRICS, SUPPORTED_RESOURCE_METRICS
        # Unlike evaluator_type, a resource metric name+unit MAY be
        # legitimately shared by more than one collector (resources.py's
        # own DuplicateResourceMetricError docstring: "two independent
        # collectors both legitimately reporting cpu_percent... fine").
        # Removing a metric here is only safe if no OTHER still-AVAILABLE
        # plugin also currently declares it, and it was never one of the
        # permanent built-ins.
        still_claimed = {
            d.metric
            for other in registry.records.values()
            if other is not existing and other.status == PluginStatus.AVAILABLE
            and other.descriptor is not None and other.descriptor.plugin_type == PluginType.RESOURCE_COLLECTOR
            and other.instance is not None
            for d in other.instance.available_metrics()
        }
        for d in existing.instance.available_metrics():
            if (d.metric not in BUILT_IN_RESOURCE_METRICS and d.metric not in still_claimed
                    and SUPPORTED_RESOURCE_METRICS.get(d.metric) == d.unit):
                del SUPPORTED_RESOURCE_METRICS[d.metric]


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
        _rollback_registration_side_effects(existing, registry)
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
        loaded = entry_point.load()
        instance = loaded() if callable(loaded) else loaded
        # A zero-arg callable entry point (the documented convention - see
        # docs/connector-api.md) doubles as the "make me a fresh one"
        # factory a connector-shaped plugin needs one-per-sensor-id
        # (Phase 102). If a plugin instead points its entry point at an
        # already-constructed object, there is no way to mint a second
        # independent one, so the same shared instance is reused - no
        # worse than v0.8's single global instance, never a crash.
        factory = loaded if callable(loaded) else (lambda inst=instance: inst)
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

    # An EVALUATOR-type plugin also needs its own evaluator_type accepted
    # into EVALUATOR_REGISTRY (v0.9, Phase 98) - a SEPARATE namespace
    # from plugin_id, checked independently: two plugins can have
    # different plugin_ids yet collide on the same evaluator_type, and
    # that collision is rejected here, before this plugin is ever
    # reported AVAILABLE.
    if descriptor.plugin_type == PluginType.EVALUATOR:
        from app.domain.evaluators import DuplicateEvaluatorTypeError, register_evaluator
        try:
            register_evaluator(instance)
        except DuplicateEvaluatorTypeError as e:
            _register(registry, PluginRecord(
                plugin_id=plugin_id, status=PluginStatus.LOAD_FAILED, descriptor=descriptor, instance=None,
                error=str(e), distribution_name=distribution_name, distribution_version=distribution_version,
            ))
            return

    # A RESOURCE_COLLECTOR-type plugin's own available_metrics() are
    # unioned into SUPPORTED_RESOURCE_METRICS (v0.9, Phase 99) - a new
    # metric name is valid only once a registered plugin actually
    # declares it, never a permanently open vocabulary. All-or-nothing:
    # a unit conflict on any one declared metric fails the whole
    # plugin's registration, never a half-applied metric set.
    if descriptor.plugin_type == PluginType.RESOURCE_COLLECTOR:
        from app.domain.resources import DuplicateResourceMetricError, register_resource_metrics
        try:
            register_resource_metrics(instance.available_metrics())
        except DuplicateResourceMetricError as e:
            _register(registry, PluginRecord(
                plugin_id=plugin_id, status=PluginStatus.LOAD_FAILED, descriptor=descriptor, instance=None,
                error=str(e), distribution_name=distribution_name, distribution_version=distribution_version,
            ))
            return

    _register(registry, PluginRecord(
        plugin_id=plugin_id, status=PluginStatus.AVAILABLE, descriptor=descriptor, instance=instance,
        factory=factory, error=None, distribution_name=distribution_name, distribution_version=distribution_version,
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
        register_built_in(
            registry, RtspSensorConnector(ros_bridge), source='multisens',
            factory=lambda: RtspSensorConnector(ros_bridge),
        )

    resolved_entry_points = (
        entry_points if entry_points is not None
        else importlib.metadata.entry_points(group=ENTRY_POINT_GROUP)
    )
    for entry_point in resolved_entry_points:
        _discover_one(registry, entry_point, disabled)

    return registry
