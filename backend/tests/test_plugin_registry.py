"""Phase 94 (v0.9): plugin discovery and the `PluginRegistry`. Entry
points are injected as simple fake objects (`.name`/`.load()`/`.dist`) -
`discover_plugins(entry_points=...)` never calls the real
`importlib.metadata.entry_points()` when a list is supplied, so these
tests exercise the exact same code path a real installed plugin would
hit without needing to actually build and pip-install a package.
"""
from types import SimpleNamespace

import pytest
from app.plugins.registry import PluginStatus, discover_plugins
from multisens_sdk import MULTISENS_PLUGIN_API_VERSION, PluginDescriptor, PluginType

BUILT_IN_EVALUATOR_IDS = {
    'multisens.builtin.evaluator.classification',
    'multisens.builtin.evaluator.object_detection',
    'multisens.builtin.evaluator.regression',
}


class _FakePlugin:
    """Minimal - only `descriptor()` matters for these registry-level
    tests; runtime methods (`start`/`evaluate`/...) belong to Phase 95+'s
    own connector-specific tests."""
    def __init__(self, plugin_id: str, api_version: str = MULTISENS_PLUGIN_API_VERSION,
                 plugin_type: PluginType = PluginType.SENSOR_CONNECTOR):
        self._descriptor = PluginDescriptor(
            plugin_id=plugin_id, name=plugin_id, version='0.1.0', plugin_type=plugin_type,
            api_version=api_version, author='Test', license='Apache-2.0',
        )

    def descriptor(self) -> PluginDescriptor:
        return self._descriptor


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
