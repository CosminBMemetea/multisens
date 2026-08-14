"""Contract-test helpers for plugin authors (v0.9, Phase 100) - opt-in
via `pip install multisens-sdk[testing]`, so `pytest` never becomes a
forced runtime dependency of every plugin. Plain, framework-agnostic
assertion functions (`assert*`, raising a plain `AssertionError` with a
clear message on failure) - never a custom test framework, never
presuming how a plugin author organizes their own test suite. Every
function here works equally well called from `pytest`, `unittest`, or a
bare script.
"""
from __future__ import annotations

from typing import Any, Callable

from multisens_sdk.evaluators import EvaluatorOutput, MetricDescriptor
from multisens_sdk.models import ResourceObservation
from multisens_sdk.plugin import ConnectorHealth, ConnectorState, PluginDescriptor, PluginType


def assert_valid_plugin_descriptor(descriptor: PluginDescriptor) -> None:
    """Checks `descriptor()`'s own return value against every rule
    docs/plugin-sdk.md documents for `PluginDescriptor` and plugin
    identity: `plugin_id` shape (`namespace.name`, lowercase,
    `[a-z0-9_.-]+`), non-empty `name`/`version`/`api_version`/`author`/
    `license`, and a genuine `PluginType` member."""
    assert isinstance(descriptor, PluginDescriptor), \
        f'expected a PluginDescriptor, got {type(descriptor).__name__}'
    assert descriptor.plugin_id, 'plugin_id must not be empty'
    segments = descriptor.plugin_id.split('.')
    assert len(segments) >= 2, (
        f"plugin_id '{descriptor.plugin_id}' should have at least two dot-separated segments "
        f"(e.g. 'namespace.name') - see docs/plugin-sdk.md#plugin-identity"
    )
    assert descriptor.plugin_id == descriptor.plugin_id.lower(), \
        f"plugin_id '{descriptor.plugin_id}' must be lowercase"
    assert all(c.isalnum() or c in '._-' for c in descriptor.plugin_id), \
        f"plugin_id '{descriptor.plugin_id}' must only contain [a-z0-9_.-]"
    assert descriptor.name, 'name must not be empty'
    assert descriptor.version, 'version must not be empty'
    assert isinstance(descriptor.plugin_type, PluginType), \
        f'plugin_type must be a PluginType, got {descriptor.plugin_type!r}'
    assert descriptor.api_version, 'api_version must not be empty'
    assert descriptor.author, 'author must not be empty - identify yourself to operators installing this plugin'
    assert descriptor.license, \
        'license must not be empty - every plugin controls its own license (docs/plugin-sdk.md)'


def assert_health_contract(health: ConnectorHealth) -> None:
    """Checks a `ConnectorHealth` value against its own documented
    shape - a genuine `ConnectorState`, a non-negative-or-`None`
    `last_sample_age_s`, an optional string `message`, and `details`
    that's always a dict (never `None` - an empty dict for "nothing
    extra to report," the same "no denominator, no fabricated value"
    discipline used everywhere else in MultiSens, applied to "no details,
    say so with an empty dict, not a missing one")."""
    assert isinstance(health, ConnectorHealth), f'expected a ConnectorHealth, got {type(health).__name__}'
    assert isinstance(health.state, ConnectorState), f'state must be a ConnectorState, got {health.state!r}'
    if health.last_sample_age_s is not None:
        assert health.last_sample_age_s >= 0, \
            f'last_sample_age_s must be >= 0 or None, got {health.last_sample_age_s}'
    if health.message is not None:
        assert isinstance(health.message, str), \
            f'message must be a string or None, got {type(health.message).__name__}'
    assert isinstance(health.details, dict), \
        f'details must always be a dict (never None), got {type(health.details).__name__}'


def assert_connector_lifecycle(connector: Any, *, configure: Callable[[], None]) -> None:
    """Exercises a connector-shaped plugin (`SensorConnector`/
    `PredictionConnector`/`GroundTruthConnector`/`ResourceCollector`)
    through `configure -> start -> stop`, asserting the `ConnectorHealth`
    contract holds at every step and `health().state` is a plausible
    post-`start()` value. `configure` is a zero-arg callable that invokes
    the plugin's own `configure()` with whatever arguments its specific
    Protocol requires - the one signature difference
    (`SensorConnector.configure` takes a `sensor_id`, the others don't)
    this helper can't paper over generically; pass a small lambda/closure
    from your own test."""
    configure()
    assert_health_contract(connector.health())

    connector.start()
    health = connector.health()
    assert_health_contract(health)
    assert health.state in (ConnectorState.RUNNING, ConnectorState.STARTING, ConnectorState.DEGRADED), (
        f'health().state after start() was {health.state} - expected RUNNING, STARTING, or DEGRADED'
    )

    connector.stop()
    assert_health_contract(connector.health())


def assert_metric_descriptors_valid(descriptors: list[MetricDescriptor]) -> None:
    """Checks an `EvaluatorPlugin.metric_descriptors()` return value:
    every entry is a real `MetricDescriptor` with a non-empty, unique
    `id`, `type == 'float'` (the only type this SDK version supports),
    and a `higher_is_better` that's genuinely `True`/`False`/`None`."""
    ids_seen: set[str] = set()
    for d in descriptors:
        assert isinstance(d, MetricDescriptor), f'expected a MetricDescriptor, got {type(d).__name__}'
        assert d.id, 'MetricDescriptor.id must not be empty'
        assert d.id not in ids_seen, f"duplicate metric id '{d.id}' in metric_descriptors()"
        ids_seen.add(d.id)
        assert d.type == 'float', f"MetricDescriptor.type must be 'float', got {d.type!r}"
        assert d.higher_is_better in (True, False, None), \
            f'higher_is_better must be True, False, or None, got {d.higher_is_better!r}'


def assert_evaluator_output_shape(output: EvaluatorOutput) -> None:
    """Checks an `EvaluatorPlugin.evaluate()` return value: the four
    frame-count fields are non-negative ints, every `metrics` value is a
    `float` or `None` (never a fabricated placeholder), and `details` is
    a dict or `None`."""
    assert isinstance(output, EvaluatorOutput), f'expected an EvaluatorOutput, got {type(output).__name__}'
    for field_name in ('sample_count', 'matched_samples', 'unmatched_predictions', 'unmatched_ground_truth'):
        value = getattr(output, field_name)
        assert isinstance(value, int) and value >= 0, f'{field_name} must be a non-negative int, got {value!r}'
    assert isinstance(output.metrics, dict), f'metrics must be a dict, got {type(output.metrics).__name__}'
    for key, value in output.metrics.items():
        assert value is None or isinstance(value, (int, float)), (
            f"metrics['{key}'] must be a float or None (never a fabricated placeholder), got {value!r}"
        )
    assert output.details is None or isinstance(output.details, dict), \
        f'details must be a dict or None, got {type(output.details).__name__}'


def assert_evaluator_deterministic(evaluate: Callable[[], EvaluatorOutput]) -> None:
    """Calls the supplied zero-arg `evaluate` closure twice and asserts
    identical `metrics` - the same input must always produce the same
    output (this project's own "boring, predictable plugins"
    preference, docs/plugin-sdk.md), never a source of nondeterminism a
    caller can't reproduce."""
    first = evaluate()
    second = evaluate()
    assert first.metrics == second.metrics, (
        f'evaluate() produced different metrics for the identical input across two calls: '
        f'{first.metrics!r} != {second.metrics!r}'
    )


def assert_resource_observation_shape(observation: ResourceObservation) -> None:
    """Checks a `ResourceCollector.sample()` item: non-empty `unit`/
    `source`, and the value-vs-quality consistency rule
    (`value is None` iff `quality == 'unavailable'`) - already enforced
    by `ResourceObservation`'s own pydantic validators at construction
    time, restated here as an explicit, readable assertion a plugin
    author can call without needing to understand pydantic internals."""
    assert isinstance(observation, ResourceObservation), \
        f'expected a ResourceObservation, got {type(observation).__name__}'
    assert observation.unit, 'unit must not be empty'
    assert observation.source, 'source must not be empty'
    if observation.quality == 'unavailable':
        assert observation.value is None, "value must be None when quality is 'unavailable'"
    else:
        assert observation.value is not None, f"value must not be None when quality is '{observation.quality}'"
