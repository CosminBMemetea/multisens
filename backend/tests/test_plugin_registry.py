"""Phase 94 (v0.9): plugin discovery and the `PluginRegistry`. Entry
points are injected as simple fake objects (`.name`/`.load()`/`.dist`) -
`discover_plugins(entry_points=...)` never calls the real
`importlib.metadata.entry_points()` when a list is supplied, so these
tests exercise the exact same code path a real installed plugin would
hit without needing to actually build and pip-install a package.
"""
from types import SimpleNamespace

import pytest
from app.domain.evaluators import EVALUATOR_REGISTRY
from app.domain.resources import SUPPORTED_RESOURCE_METRICS
from app.plugins.registry import PluginStatus, discover_plugins
from multisens_sdk import MULTISENS_PLUGIN_API_VERSION, PluginDescriptor, PluginType, ResourceMetricDescriptor

BUILT_IN_EVALUATOR_IDS = {
    'multisens.builtin.evaluator.classification',
    'multisens.builtin.evaluator.object_detection',
    'multisens.builtin.evaluator.regression',
}


class _FakePlugin:
    """Minimal - only `descriptor()` matters for these registry-level
    tests; runtime methods (`start`/`evaluate`/...) belong to Phase 95+'s
    own connector-specific tests. `available_metrics()` is here purely so
    a PluginType.RESOURCE_COLLECTOR-typed instance satisfies Phase 99's
    own registration hook (app/plugins/registry.py calls it
    unconditionally for that plugin type) - empty by default, meaning
    "declares no new metrics," never exercised further by these
    registry-level tests."""
    def __init__(self, plugin_id: str, api_version: str = MULTISENS_PLUGIN_API_VERSION,
                 plugin_type: PluginType = PluginType.SENSOR_CONNECTOR):
        self._descriptor = PluginDescriptor(
            plugin_id=plugin_id, name=plugin_id, version='0.1.0', plugin_type=plugin_type,
            api_version=api_version, author='Test', license='Apache-2.0',
        )

    def descriptor(self) -> PluginDescriptor:
        return self._descriptor

    def available_metrics(self) -> list:
        return []


class _RaisingDescriptorPlugin:
    """Simulates a malformed plugin whose own `descriptor()` call raises -
    never propagates out of discovery."""
    def descriptor(self) -> PluginDescriptor:
        raise ValueError('descriptor() deliberately broken for this test')


def _entry_point(name: str, factory, dist_name: str = 'fake-dist', dist_version: str = '0.1.0'):
    return SimpleNamespace(
        name=name, load=lambda: factory,
        dist=SimpleNamespace(name=dist_name, version=dist_version),
    )


def _raising_load_entry_point(name: str, dist_name: str = 'fake-dist'):
    def _load():
        raise ImportError(f"No module named '{name}' - simulated import failure")
    return SimpleNamespace(name=name, load=_load, dist=SimpleNamespace(name=dist_name, version='0.1.0'))


# --- bullet: zero plugins - just the built-ins ------------------------------

def test_zero_external_plugins_still_registers_the_three_built_in_evaluators():
    registry = discover_plugins(entry_points=[])
    available_ids = {r.plugin_id for r in registry.available()}
    assert available_ids == BUILT_IN_EVALUATOR_IDS
    for plugin_id in BUILT_IN_EVALUATOR_IDS:
        record = registry.get(plugin_id)
        assert record.status == PluginStatus.AVAILABLE
        assert record.instance is not None
        assert record.distribution_name == 'multisens'


# --- bullet: one plugin ------------------------------------------------------

def test_one_valid_external_plugin_registers_as_available():
    plugin = _FakePlugin('acme.sensor.mock')
    registry = discover_plugins(entry_points=[_entry_point('acme.sensor.mock', plugin)])
    record = registry.get('acme.sensor.mock')
    assert record.status == PluginStatus.AVAILABLE
    assert record.instance is plugin
    assert record.descriptor.plugin_id == 'acme.sensor.mock'
    assert record.distribution_name == 'fake-dist'


# --- bullet: multiple plugin types ------------------------------------------

def test_multiple_plugin_types_all_register_independently():
    plugins = [
        _FakePlugin('acme.sensor.mock', plugin_type=PluginType.SENSOR_CONNECTOR),
        _FakePlugin('acme.prediction.mock', plugin_type=PluginType.PREDICTION_CONNECTOR),
        _FakePlugin('acme.groundtruth.mock', plugin_type=PluginType.GROUND_TRUTH_CONNECTOR),
        _FakePlugin('acme.resource.mock', plugin_type=PluginType.RESOURCE_COLLECTOR),
    ]
    entry_points = [_entry_point(p.descriptor().plugin_id, p) for p in plugins]
    registry = discover_plugins(entry_points=entry_points)
    for plugin in plugins:
        record = registry.get(plugin.descriptor().plugin_id)
        assert record.status == PluginStatus.AVAILABLE
        assert record.descriptor.plugin_type == plugin.descriptor().plugin_type
    # Built-ins are still there too - external discovery never displaces them.
    assert BUILT_IN_EVALUATOR_IDS <= {r.plugin_id for r in registry.available()}


# --- bullet: incompatible API version ---------------------------------------

def test_incompatible_api_version_is_incompatible_never_loaded_or_called():
    plugin = _FakePlugin('acme.sensor.futuristic', api_version='2')
    registry = discover_plugins(entry_points=[_entry_point('acme.sensor.futuristic', plugin)])
    record = registry.get('acme.sensor.futuristic')
    assert record.status == PluginStatus.INCOMPATIBLE
    assert record.instance is None  # descriptor is readable, but nothing is ever called on it
    assert record.descriptor is not None
    assert '2' in record.error and MULTISENS_PLUGIN_API_VERSION in record.error


# --- bullet: malformed descriptor -------------------------------------------

def test_malformed_descriptor_raising_is_load_failed_not_a_crash():
    registry = discover_plugins(entry_points=[
        _entry_point('acme.sensor.broken', _RaisingDescriptorPlugin()),
    ])
    record = registry.get('acme.sensor.broken')
    assert record.status == PluginStatus.LOAD_FAILED
    assert record.instance is None
    assert 'deliberately broken' in record.error


def test_descriptor_plugin_id_mismatch_with_entry_point_name_is_load_failed():
    # The plugin's own descriptor disagrees with the name it was
    # registered under - never silently trust one over the other.
    plugin = _FakePlugin('acme.sensor.actual-id')
    registry = discover_plugins(entry_points=[_entry_point('acme.sensor.registered-as', plugin)])
    record = registry.get('acme.sensor.registered-as')
    assert record.status == PluginStatus.LOAD_FAILED
    assert 'does not match' in record.error


# --- bullet: duplicate plugin id ---------------------------------------------

def test_duplicate_plugin_id_across_two_distributions_rejects_both_deterministically():
    first = _FakePlugin('acme.sensor.mock')
    second = _FakePlugin('acme.sensor.mock')
    registry = discover_plugins(entry_points=[
        _entry_point('acme.sensor.mock', first, dist_name='dist-one'),
        _entry_point('acme.sensor.mock', second, dist_name='dist-two'),
    ])
    record = registry.get('acme.sensor.mock')
    assert record.status == PluginStatus.LOAD_FAILED
    assert 'duplicate plugin_id' in record.error
    assert 'dist-one' in record.error and 'dist-two' in record.error
    assert record.instance is None


def test_duplicate_plugin_id_against_a_built_in_evaluator_rejects_both():
    fake = _FakePlugin('multisens.builtin.evaluator.classification', plugin_type=PluginType.EVALUATOR)
    registry = discover_plugins(entry_points=[
        _entry_point('multisens.builtin.evaluator.classification', fake, dist_name='acme-imitation'),
    ])
    record = registry.get('multisens.builtin.evaluator.classification')
    assert record.status == PluginStatus.LOAD_FAILED
    assert 'duplicate plugin_id' in record.error
    # The real built-in evaluator must never keep silently running as if
    # nothing happened - a collision means BOTH sides are untrusted now.
    assert record.instance is None


# --- bullet: duplicate plugin id must roll back registration side effects ---
# v0.9 bug hunt, issue #117: register_evaluator()/register_resource_metrics()
# mutate EVALUATOR_REGISTRY/SUPPORTED_RESOURCE_METRICS - separate global
# namespaces from PluginRegistry itself - the moment the FIRST of two
# same-plugin_id entries is processed. When the SECOND entry arrives and
# both are marked LOAD_FAILED ("neither is used"), that mutation must be
# undone too, or the "unusable" plugin stays live and dispatchable.

@pytest.fixture
def clean_evaluator_registry():
    original = dict(EVALUATOR_REGISTRY)
    yield EVALUATOR_REGISTRY
    EVALUATOR_REGISTRY.clear()
    EVALUATOR_REGISTRY.update(original)


@pytest.fixture
def clean_supported_resource_metrics():
    original = dict(SUPPORTED_RESOURCE_METRICS)
    yield SUPPORTED_RESOURCE_METRICS
    SUPPORTED_RESOURCE_METRICS.clear()
    SUPPORTED_RESOURCE_METRICS.update(original)


class _FakeEvaluatorPlugin:
    def __init__(self, plugin_id: str, evaluator_type: str):
        self.evaluator_type = evaluator_type
        self._descriptor = PluginDescriptor(
            plugin_id=plugin_id, name=plugin_id, version='0.1.0', plugin_type=PluginType.EVALUATOR,
            api_version=MULTISENS_PLUGIN_API_VERSION, author='Test', license='Apache-2.0',
        )

    def descriptor(self) -> PluginDescriptor:
        return self._descriptor


class _FakeResourceCollectorPlugin:
    def __init__(self, plugin_id: str, metrics: list[ResourceMetricDescriptor]):
        self._metrics = metrics
        self._descriptor = PluginDescriptor(
            plugin_id=plugin_id, name=plugin_id, version='0.1.0', plugin_type=PluginType.RESOURCE_COLLECTOR,
            api_version=MULTISENS_PLUGIN_API_VERSION, author='Test', license='Apache-2.0',
        )

    def descriptor(self) -> PluginDescriptor:
        return self._descriptor

    def available_metrics(self) -> list[ResourceMetricDescriptor]:
        return self._metrics


def test_duplicate_plugin_id_unregisters_the_first_plugins_evaluator_type(clean_evaluator_registry):
    first = _FakeEvaluatorPlugin('acme.evaluator.dup', 'acme_custom')
    second = _FakeEvaluatorPlugin('acme.evaluator.dup', 'acme_custom_v2')
    registry = discover_plugins(entry_points=[
        _entry_point('acme.evaluator.dup', first, dist_name='dist-one'),
        _entry_point('acme.evaluator.dup', second, dist_name='dist-two'),
    ])
    record = registry.get('acme.evaluator.dup')
    assert record.status == PluginStatus.LOAD_FAILED
    # The whole point: the registry says "neither is used", so neither
    # evaluator_type may still be dispatchable through EVALUATOR_REGISTRY.
    assert 'acme_custom' not in EVALUATOR_REGISTRY
    assert 'acme_custom_v2' not in EVALUATOR_REGISTRY


def test_duplicate_plugin_id_never_touches_a_built_in_evaluator_type(clean_evaluator_registry):
    # A plugin_id collision against a BUILT-IN goes through a different
    # branch (register_built_in) that never calls register_evaluator in
    # the first place - the built-in's own EVALUATOR_REGISTRY entry (its
    # permanent, non-plugin-sourced seed) must survive untouched.
    fake = _FakePlugin('multisens.builtin.evaluator.classification', plugin_type=PluginType.EVALUATOR)
    discover_plugins(entry_points=[
        _entry_point('multisens.builtin.evaluator.classification', fake, dist_name='acme-imitation'),
    ])
    assert 'classification' in EVALUATOR_REGISTRY


def test_duplicate_plugin_id_unregisters_the_first_plugins_new_resource_metric(clean_supported_resource_metrics):
    first = _FakeResourceCollectorPlugin(
        'acme.resource.dup', [ResourceMetricDescriptor(metric='battery_percent', unit='%')],
    )
    second = _FakeResourceCollectorPlugin(
        'acme.resource.dup', [ResourceMetricDescriptor(metric='battery_percent', unit='%')],
    )
    registry = discover_plugins(entry_points=[
        _entry_point('acme.resource.dup', first, dist_name='dist-one'),
        _entry_point('acme.resource.dup', second, dist_name='dist-two'),
    ])
    assert registry.get('acme.resource.dup').status == PluginStatus.LOAD_FAILED
    assert 'battery_percent' not in SUPPORTED_RESOURCE_METRICS


def test_duplicate_plugin_id_never_removes_a_built_in_resource_metric(clean_supported_resource_metrics):
    # The invalidated plugin happened to also (legitimately) declare a
    # built-in metric name+unit - removing 'cpu_percent' entirely would
    # break every other consumer of the permanent baseline.
    first = _FakeResourceCollectorPlugin('acme.resource.dup', [ResourceMetricDescriptor(metric='cpu_percent', unit='%')])
    second = _FakeResourceCollectorPlugin('acme.resource.dup', [ResourceMetricDescriptor(metric='cpu_percent', unit='%')])
    discover_plugins(entry_points=[
        _entry_point('acme.resource.dup', first, dist_name='dist-one'),
        _entry_point('acme.resource.dup', second, dist_name='dist-two'),
    ])
    assert SUPPORTED_RESOURCE_METRICS['cpu_percent'] == '%'


def test_duplicate_plugin_id_never_removes_a_metric_still_claimed_by_another_live_plugin(
    clean_supported_resource_metrics,
):
    # 'shared_metric' is newly introduced by the first (soon-to-be-
    # invalidated) plugin, but a THIRD, unrelated, still-AVAILABLE plugin
    # also legitimately declares it - it must survive the rollback.
    invalidated_one = _FakeResourceCollectorPlugin(
        'acme.resource.dup', [ResourceMetricDescriptor(metric='shared_metric', unit='x')],
    )
    invalidated_two = _FakeResourceCollectorPlugin(
        'acme.resource.dup', [ResourceMetricDescriptor(metric='shared_metric', unit='x')],
    )
    still_alive = _FakeResourceCollectorPlugin(
        'acme.resource.other', [ResourceMetricDescriptor(metric='shared_metric', unit='x')],
    )
    registry = discover_plugins(entry_points=[
        _entry_point('acme.resource.dup', invalidated_one, dist_name='dist-one'),
        _entry_point('acme.resource.other', still_alive, dist_name='dist-three'),
        _entry_point('acme.resource.dup', invalidated_two, dist_name='dist-two'),
    ])
    assert registry.get('acme.resource.dup').status == PluginStatus.LOAD_FAILED
    assert registry.get('acme.resource.other').status == PluginStatus.AVAILABLE
    assert SUPPORTED_RESOURCE_METRICS['shared_metric'] == 'x'


# --- bullet: import failure ---------------------------------------------------

def test_entry_point_load_raising_import_error_is_load_failed_not_a_crash():
    registry = discover_plugins(entry_points=[_raising_load_entry_point('acme.sensor.missing-dep')])
    record = registry.get('acme.sensor.missing-dep')
    assert record.status == PluginStatus.LOAD_FAILED
    assert record.instance is None
    assert 'simulated import failure' in record.error


# --- bullet: disabled plugin ---------------------------------------------------

def test_disabled_plugin_is_never_loaded_at_all():
    load_was_called = False

    def _factory():
        nonlocal load_was_called
        load_was_called = True
        return _FakePlugin('acme.sensor.should-not-load')

    entry_point = SimpleNamespace(
        name='acme.sensor.should-not-load', load=lambda: _factory,
        dist=SimpleNamespace(name='fake-dist', version='0.1.0'),
    )
    registry = discover_plugins(entry_points=[entry_point], disabled_plugin_ids=['acme.sensor.should-not-load'])
    record = registry.get('acme.sensor.should-not-load')
    assert record.status == PluginStatus.DISABLED
    assert record.instance is None
    assert record.descriptor is None
    # The whole point: disabling means the plugin's own code never runs.
    assert load_was_called is False


# --- bullet: core continues after one optional plugin fails ------------------

def test_one_broken_plugin_never_prevents_others_from_registering():
    good_a = _FakePlugin('acme.sensor.good-a')
    good_b = _FakePlugin('acme.sensor.good-b')
    registry = discover_plugins(entry_points=[
        _entry_point('acme.sensor.good-a', good_a),
        _raising_load_entry_point('acme.sensor.broken-middle'),
        _entry_point('acme.sensor.good-b', good_b),
    ])
    assert registry.get('acme.sensor.good-a').status == PluginStatus.AVAILABLE
    assert registry.get('acme.sensor.broken-middle').status == PluginStatus.LOAD_FAILED
    assert registry.get('acme.sensor.good-b').status == PluginStatus.AVAILABLE
    # The three built-in evaluators are also still fine - one broken
    # external plugin never touches them.
    assert BUILT_IN_EVALUATOR_IDS <= {r.plugin_id for r in registry.available()}


# --- factory field (v0.9, Phase 102) ----------------------------------------

def test_built_in_evaluator_factory_defaults_to_reusing_the_singleton_instance():
    # Built-in evaluators have always been shared singletons - Phase 102
    # doesn't change that, it just makes the "how do I get one" access
    # path explicit and uniform across every plugin type.
    registry = discover_plugins(entry_points=[])
    record = registry.get('multisens.builtin.evaluator.classification')
    assert record.factory is not None
    assert record.factory() is record.instance


def test_external_plugin_registered_via_a_callable_factory_captures_it_and_yields_fresh_objects():
    build_count = 0

    def _factory():
        nonlocal build_count
        build_count += 1
        return _FakePlugin('acme.sensor.multi-instance')

    entry_point = SimpleNamespace(
        name='acme.sensor.multi-instance', load=lambda: _factory,
        dist=SimpleNamespace(name='fake-dist', version='0.1.0'),
    )
    registry = discover_plugins(entry_points=[entry_point])
    record = registry.get('acme.sensor.multi-instance')
    assert record.status == PluginStatus.AVAILABLE
    assert build_count == 1  # discovery itself calls the factory exactly once, to obtain the descriptor

    first = record.factory()
    second = record.factory()
    assert build_count == 3
    assert first is not second  # a fresh object each call - never the same shared instance

    assert record.instance is not first and record.instance is not second


def test_external_plugin_registered_as_a_bare_instance_falls_back_to_reusing_it():
    # An entry point may point straight at an already-constructed object
    # rather than a zero-arg factory function - there's no way to mint a
    # second independent one in that case, so the same instance is reused
    # (no worse than the pre-Phase-102 single-global-instance behavior).
    plugin = _FakePlugin('acme.sensor.singleton-only')
    registry = discover_plugins(entry_points=[_entry_point('acme.sensor.singleton-only', plugin)])
    record = registry.get('acme.sensor.singleton-only')
    assert record.factory() is plugin
    assert record.factory() is record.instance


def test_discover_plugins_never_raises_regardless_of_how_badly_a_plugin_is_broken():
    class _ExplodesOnEverything:
        def descriptor(self):
            raise RuntimeError('boom')

    def _exploding_factory():
        raise RuntimeError('factory itself exploded')

    entry_points = [
        _raising_load_entry_point('acme.a'),
        _entry_point('acme.b', _ExplodesOnEverything()),
        SimpleNamespace(name='acme.c', load=lambda: _exploding_factory,
                         dist=SimpleNamespace(name='fake-dist', version='0.1.0')),
    ]
    # Must not raise - this call itself is the assertion.
    registry = discover_plugins(entry_points=entry_points)
    for plugin_id in ('acme.a', 'acme.b', 'acme.c'):
        assert registry.get(plugin_id).status == PluginStatus.LOAD_FAILED
