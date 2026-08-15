"""v0.9.1 (issue #111): `build_resource_collector_instances()`/
`start_resource_collection()`/`stop_resource_collection()` - the
session-bound live-collection wiring that closes the last "plugin
discovers as AVAILABLE and then sits inert forever" gap
`test_poll_connector_wiring.py` already closed for prediction/ground
-truth connectors.

Deliberately NOT a new runner class: `ResourceCollectorInstance.sample()`
already matches `PollRunner`'s own `poll` shape exactly, so
`start_resource_collection()` reuses `PollRunner` unmodified - the direct
regression test below proves a real row lands in the database through
the exact same background-thread path.
"""
import time
from datetime import datetime, timezone

from app.domain.models import Scenario, Session
from app.persistence import db as db_module
from app.persistence import repository as repo
from app.plugins.manager import (
    build_resource_collector_instances,
    start_resource_collection,
    stop_resource_collection,
)
from app.plugins.registry import PluginRecord, PluginRegistry, PluginStatus
from multisens_sdk import (
    MULTISENS_PLUGIN_API_VERSION,
    ConnectorConfigError,
    ConnectorHealth,
    ConnectorState,
    PluginDescriptor,
    PluginType,
    ResourceMetricDescriptor,
    ResourceObservation,
)


class _FakeResourceCollector:
    def __init__(self):
        self.configured_with: dict | None = None
        self.started = False
        self.next_sample_result: list = []
        self.fail_configure = False

    def descriptor(self) -> PluginDescriptor:
        return PluginDescriptor(
            plugin_id='acme.resource.fake', name='Fake Resource Collector', version='1.0.0',
            plugin_type=PluginType.RESOURCE_COLLECTOR, api_version=MULTISENS_PLUGIN_API_VERSION,
        )

    def available_metrics(self) -> list[ResourceMetricDescriptor]:
        return [ResourceMetricDescriptor(metric='fake_metric', unit='x')]

    def configure(self, config: dict) -> None:
        if self.fail_configure:
            raise ConnectorConfigError('deliberately broken configure()')
        self.configured_with = config

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        self.started = False

    def health(self) -> ConnectorHealth:
        return ConnectorHealth(state=ConnectorState.RUNNING if self.started else ConnectorState.STOPPED)

    def sample(self) -> list[ResourceObservation]:
        return self.next_sample_result


class _FakeEvaluatorPlugin:
    def descriptor(self) -> PluginDescriptor:
        return PluginDescriptor(
            plugin_id='acme.evaluator.fake', name='Fake Evaluator', version='1.0.0',
            plugin_type=PluginType.EVALUATOR, api_version=MULTISENS_PLUGIN_API_VERSION,
        )


def _registry_with_fake_plugins() -> PluginRegistry:
    registry = PluginRegistry()
    plugin = _FakeResourceCollector()
    registry.records['acme.resource.fake'] = PluginRecord(
        plugin_id='acme.resource.fake', status=PluginStatus.AVAILABLE,
        descriptor=plugin.descriptor(), instance=plugin,
        factory=lambda: _FakeResourceCollector(), distribution_name='acme',
    )
    evaluator_plugin = _FakeEvaluatorPlugin()
    registry.records['acme.evaluator.fake'] = PluginRecord(
        plugin_id='acme.evaluator.fake', status=PluginStatus.AVAILABLE,
        descriptor=evaluator_plugin.descriptor(), instance=evaluator_plugin,
        factory=lambda: _FakeEvaluatorPlugin(), distribution_name='acme',
    )
    return registry


def _failing_resource_collector() -> _FakeResourceCollector:
    collector = _FakeResourceCollector()
    collector.fail_configure = True
    return collector


# --- build_resource_collector_instances(): config-entry validation ---------

def test_entry_missing_id_or_plugin_is_skipped_not_a_crash():
    specs = [{'plugin': 'acme.resource.fake'}, {'id': 'no-plugin-named'}]
    instances = build_resource_collector_instances(specs, _registry_with_fake_plugins())
    assert instances == {}


def test_unknown_plugin_is_skipped_not_a_crash():
    specs = [{'id': 'x', 'plugin': 'does.not.exist'}]
    instances = build_resource_collector_instances(specs, _registry_with_fake_plugins())
    assert instances == {}


def test_wrong_typed_plugin_is_skipped_not_a_crash():
    specs = [{'id': 'x', 'plugin': 'acme.evaluator.fake'}]
    instances = build_resource_collector_instances(specs, _registry_with_fake_plugins())
    assert instances == {}


def test_invalid_poll_interval_is_skipped():
    for bad_interval in (-1, 0, float('nan'), 'not-a-number', True):
        specs = [{'id': 'x', 'plugin': 'acme.resource.fake', 'poll_interval_s': bad_interval}]
        instances = build_resource_collector_instances(specs, _registry_with_fake_plugins())
        assert instances == {}, f'poll_interval_s={bad_interval!r} should have been rejected'


def test_valid_entry_builds_but_does_not_configure_or_start():
    # The whole point of the two-step split: construction happens at
    # boot, with no session context yet - configure()/start() only ever
    # happen inside start_resource_collection(), per session.
    specs = [{'id': 'x', 'plugin': 'acme.resource.fake', 'config': {'k': 'v'}, 'poll_interval_s': 2.0}]
    instances = build_resource_collector_instances(specs, _registry_with_fake_plugins())
    assert set(instances) == {'x'}
    instance, static_config, poll_interval_s = instances['x']
    assert static_config == {'k': 'v'}
    assert poll_interval_s == 2.0
    assert instance.state == ConnectorState.STOPPED
    assert instance._plugin.configured_with is None


# --- start_resource_collection()/stop_resource_collection() ----------------

def test_start_resource_collection_configures_and_starts_every_collector():
    specs = [{'id': 'x', 'plugin': 'acme.resource.fake', 'config': {'k': 'v'}}]
    collectors = build_resource_collector_instances(specs, _registry_with_fake_plugins())
    runners = start_resource_collection('s1', 'cfg-a', 'platform-1', ['sensor-a'], collectors)
    try:
        assert set(runners) == {'x'}
        instance, runner = runners['x']
        assert instance.state == ConnectorState.RUNNING
        assert instance._plugin.configured_with == {
            'k': 'v', 'session_id': 's1', 'configuration_id': 'cfg-a',
            'platform_id': 'platform-1', 'sensor_ids': ['sensor-a'],
        }
    finally:
        stop_resource_collection(runners)


def test_start_resource_collection_never_raises_on_a_configure_failure():
    # A broken collector must never fail session start itself.
    registry = _registry_with_fake_plugins()
    registry.records['acme.resource.fake'] = PluginRecord(
        plugin_id='acme.resource.fake', status=PluginStatus.AVAILABLE,
        descriptor=_FakeResourceCollector().descriptor(), instance=None,
        distribution_name='acme', factory=_failing_resource_collector,
    )
    specs = [{'id': 'x', 'plugin': 'acme.resource.fake'}]
    collectors = build_resource_collector_instances(specs, registry)
    runners = start_resource_collection('s1', None, None, [], collectors)
    assert runners == {}  # dropped, never raised


def test_a_collector_already_running_for_another_session_is_skipped_not_raised():
    # ResourceCollectorInstance.configure() itself rejects being called
    # while RUNNING - the real safety property this design leans on for
    # the concurrent-session case. start_resource_collection() must
    # surface that as a skip, never let it escape and fail session B's
    # own /start call.
    specs = [{'id': 'x', 'plugin': 'acme.resource.fake'}]
    collectors = build_resource_collector_instances(specs, _registry_with_fake_plugins())
    runners_a = start_resource_collection('session-a', 'cfg-a', None, [], collectors)
    try:
        assert set(runners_a) == {'x'}
        # Same `collectors` dict passed again for a second, concurrent
        # session - the instance is still RUNNING for session-a.
        runners_b = start_resource_collection('session-b', 'cfg-b', None, [], collectors)
        assert runners_b == {}
    finally:
        stop_resource_collection(runners_a)


def test_stop_resource_collection_stops_both_the_thread_and_the_instance():
    specs = [{'id': 'x', 'plugin': 'acme.resource.fake'}]
    collectors = build_resource_collector_instances(specs, _registry_with_fake_plugins())
    runners = start_resource_collection('s1', None, None, [], collectors)
    instance, runner = runners['x']
    assert instance.state == ConnectorState.RUNNING

    stop_resource_collection(runners)

    assert instance.state == ConnectorState.STOPPED
    assert runner._thread is None


def test_stop_resource_collection_handles_an_empty_dict():
    stop_resource_collection({})  # must not raise


def test_a_stopped_collector_can_be_reconfigured_for_a_new_session():
    # The session-bound lifecycle depends on this: session A completes
    # (stop), then session B starts (configure+start again) using the
    # SAME instance - must not raise "already configured" or leak state
    # from session A.
    specs = [{'id': 'x', 'plugin': 'acme.resource.fake'}]
    collectors = build_resource_collector_instances(specs, _registry_with_fake_plugins())
    runners_a = start_resource_collection('session-a', 'cfg-a', None, [], collectors)
    stop_resource_collection(runners_a)

    runners_b = start_resource_collection('session-b', 'cfg-b', None, [], collectors)
    try:
        instance, _runner = runners_b['x']
        assert instance.state == ConnectorState.RUNNING
        assert instance._plugin.configured_with['session_id'] == 'session-b'
    finally:
        stop_resource_collection(runners_b)


# --- the direct regression test: a real row lands in the database ----------

def test_a_started_resource_collector_actually_samples_and_writes_to_the_database(tmp_path):
    """Before this wiring, nothing in the application ever called
    PollRunner.start() for a ResourceCollectorInstance - it would sit
    AVAILABLE forever and never ingest a row (issue #111). This builds a
    real collector from config (build_resource_collector_instances, then
    start_resource_collection - exactly what api/sessions.py's
    start_session now calls), lets it run against a real temporary
    database for a couple of sample cycles, and confirms a resource
    observation genuinely lands in the database."""
    db_path = tmp_path / 'test.db'
    conn = db_module.connect(str(db_path))
    try:
        repo.create_scenario(conn, Scenario(id='sc1', name='demo'))
        repo.create_session(conn, Session(
            id='s1', name='demo session', scenario_id='sc1', started_at=datetime.now(timezone.utc),
        ))
    finally:
        conn.close()

    def _observation(obs_id: str) -> ResourceObservation:
        now = datetime.now(timezone.utc)
        return ResourceObservation(
            id=obs_id, session_id='s1', configuration_id='cfg-a', metric='fake_metric', value=1.0,
            unit='x', quality='measured', source='fake', platform_id='platform-1', started_at=now, ended_at=now,
        )

    plugin = _FakeResourceCollector()
    plugin.next_sample_result = [_observation('obs-a')]
    registry = PluginRegistry()
    registry.records['acme.resource.fake'] = PluginRecord(
        plugin_id='acme.resource.fake', status=PluginStatus.AVAILABLE,
        descriptor=plugin.descriptor(), instance=plugin, factory=lambda: plugin, distribution_name='acme',
    )

    specs = [{'id': 'x', 'plugin': 'acme.resource.fake', 'poll_interval_s': 0.05}]
    collectors = build_resource_collector_instances(specs, registry)
    runners = start_resource_collection(
        's1', 'cfg-a', 'platform-1', [], collectors, connect=lambda: db_module.connect(str(db_path)),
    )
    try:
        assert set(runners) == {'x'}
        time.sleep(0.3)  # let the background thread actually sample a few times
    finally:
        stop_resource_collection(runners)

    conn = db_module.connect(str(db_path))
    try:
        stored = repo.list_resource_observations(conn, 's1')
    finally:
        conn.close()
    assert {o.id for o in stored} == {'obs-a'}  # genuinely persisted, not just "instance says RUNNING"
