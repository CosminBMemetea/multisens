"""v1.0-RC (issue #122): `build_inference_connector_instances()`/
`start_inference_connectors()`/`stop_inference_connectors()` - the
session-bound live-inference wiring, mirroring
`test_resource_collector_wiring.py`'s own pattern exactly for
`PREDICTION_CONNECTOR`-type plugins instead of `RESOURCE_COLLECTOR`.

Deliberately NOT a new runner class: `PredictionConnectorInstance.poll()`
already matches `PollRunner`'s own `poll` shape exactly (Phase 97), so
`start_inference_connectors()` reuses `PollRunner` unmodified - the direct
regression test below proves a real row lands in the database through
the exact same background-thread path.
"""
import time
from datetime import datetime, timezone

from app.domain.models import Scenario, Session
from app.persistence import db as db_module
from app.persistence import repository as repo
from app.plugins.manager import (
    build_inference_connector_instances,
    start_inference_connectors,
    stop_inference_connectors,
)
from app.plugins.registry import PluginRecord, PluginRegistry, PluginStatus
from multisens_sdk import (
    MULTISENS_PLUGIN_API_VERSION,
    ConnectorConfigError,
    ConnectorHealth,
    ConnectorState,
    PluginDescriptor,
    PluginType,
    Prediction,
)


class _FakeInferenceBridge:
    def __init__(self):
        self.configured_with: dict | None = None
        self.started = False
        self.next_poll_result: list = []
        self.fail_configure = False

    def descriptor(self) -> PluginDescriptor:
        return PluginDescriptor(
            plugin_id='acme.inference.fake', name='Fake Inference Bridge', version='1.0.0',
            plugin_type=PluginType.PREDICTION_CONNECTOR, api_version=MULTISENS_PLUGIN_API_VERSION,
        )

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

    def poll(self) -> list[Prediction]:
        return self.next_poll_result


class _FakeEvaluatorPlugin:
    def descriptor(self) -> PluginDescriptor:
        return PluginDescriptor(
            plugin_id='acme.evaluator.fake', name='Fake Evaluator', version='1.0.0',
            plugin_type=PluginType.EVALUATOR, api_version=MULTISENS_PLUGIN_API_VERSION,
        )


def _registry_with_fake_plugins() -> PluginRegistry:
    registry = PluginRegistry()
    plugin = _FakeInferenceBridge()
    registry.records['acme.inference.fake'] = PluginRecord(
        plugin_id='acme.inference.fake', status=PluginStatus.AVAILABLE,
        descriptor=plugin.descriptor(), instance=plugin,
        factory=lambda: _FakeInferenceBridge(), distribution_name='acme',
    )
    evaluator_plugin = _FakeEvaluatorPlugin()
    registry.records['acme.evaluator.fake'] = PluginRecord(
        plugin_id='acme.evaluator.fake', status=PluginStatus.AVAILABLE,
        descriptor=evaluator_plugin.descriptor(), instance=evaluator_plugin,
        factory=lambda: _FakeEvaluatorPlugin(), distribution_name='acme',
    )
    return registry


def _failing_inference_bridge() -> _FakeInferenceBridge:
    bridge = _FakeInferenceBridge()
    bridge.fail_configure = True
    return bridge


# --- build_inference_connector_instances(): config-entry validation --------

def test_entry_missing_id_or_plugin_is_skipped_not_a_crash():
    specs = [{'plugin': 'acme.inference.fake'}, {'id': 'no-plugin-named'}]
    instances = build_inference_connector_instances(specs, _registry_with_fake_plugins())
    assert instances == {}


def test_unknown_plugin_is_skipped_not_a_crash():
    specs = [{'id': 'x', 'plugin': 'does.not.exist'}]
    instances = build_inference_connector_instances(specs, _registry_with_fake_plugins())
    assert instances == {}


def test_wrong_typed_plugin_is_skipped_not_a_crash():
    specs = [{'id': 'x', 'plugin': 'acme.evaluator.fake'}]
    instances = build_inference_connector_instances(specs, _registry_with_fake_plugins())
    assert instances == {}


def test_invalid_poll_interval_is_skipped():
    for bad_interval in (-1, 0, float('nan'), 'not-a-number', True):
        specs = [{'id': 'x', 'plugin': 'acme.inference.fake', 'poll_interval_s': bad_interval}]
        instances = build_inference_connector_instances(specs, _registry_with_fake_plugins())
        assert instances == {}, f'poll_interval_s={bad_interval!r} should have been rejected'


def test_valid_entry_builds_but_does_not_configure_or_start():
    # The whole point of the two-step split: construction happens at
    # boot, with no session context yet - configure()/start() only ever
    # happen inside start_inference_connectors(), per session.
    specs = [{'id': 'x', 'plugin': 'acme.inference.fake', 'config': {'sensor_id': 'demo_rgb'}, 'poll_interval_s': 2.0}]
    instances = build_inference_connector_instances(specs, _registry_with_fake_plugins())
    assert set(instances) == {'x'}
    instance, static_config, poll_interval_s = instances['x']
    assert static_config == {'sensor_id': 'demo_rgb'}
    assert poll_interval_s == 2.0
    assert instance.state == ConnectorState.STOPPED
    assert instance._plugin.configured_with is None


# --- start_inference_connectors()/stop_inference_connectors() --------------

def test_start_inference_connectors_configures_and_starts_every_connector():
    specs = [{'id': 'x', 'plugin': 'acme.inference.fake', 'config': {'sensor_id': 'demo_rgb'}}]
    connectors = build_inference_connector_instances(specs, _registry_with_fake_plugins())
    runners = start_inference_connectors('s1', connectors)
    try:
        assert set(runners) == {'x'}
        instance, runner = runners['x']
        assert instance.state == ConnectorState.RUNNING
        assert instance._plugin.configured_with == {'sensor_id': 'demo_rgb', 'session_id': 's1'}
    finally:
        stop_inference_connectors(runners)


def test_start_inference_connectors_never_raises_on_a_configure_failure():
    # A broken connector must never fail session start itself.
    registry = _registry_with_fake_plugins()
    registry.records['acme.inference.fake'] = PluginRecord(
        plugin_id='acme.inference.fake', status=PluginStatus.AVAILABLE,
        descriptor=_FakeInferenceBridge().descriptor(), instance=None,
        distribution_name='acme', factory=_failing_inference_bridge,
    )
    specs = [{'id': 'x', 'plugin': 'acme.inference.fake'}]
    connectors = build_inference_connector_instances(specs, registry)
    runners = start_inference_connectors('s1', connectors)
    assert runners == {}  # dropped, never raised


def test_a_connector_already_running_for_another_session_is_skipped_not_raised():
    # PredictionConnectorInstance.configure() itself rejects being called
    # while RUNNING - the real safety property this design leans on for
    # the concurrent-session case. start_inference_connectors() must
    # surface that as a skip, never let it escape and fail session B's
    # own /start call.
    specs = [{'id': 'x', 'plugin': 'acme.inference.fake'}]
    connectors = build_inference_connector_instances(specs, _registry_with_fake_plugins())
    runners_a = start_inference_connectors('session-a', connectors)
    try:
        assert set(runners_a) == {'x'}
        runners_b = start_inference_connectors('session-b', connectors)
        assert runners_b == {}
    finally:
        stop_inference_connectors(runners_a)


def test_stop_inference_connectors_stops_both_the_thread_and_the_instance():
    specs = [{'id': 'x', 'plugin': 'acme.inference.fake'}]
    connectors = build_inference_connector_instances(specs, _registry_with_fake_plugins())
    runners = start_inference_connectors('s1', connectors)
    instance, runner = runners['x']
    assert instance.state == ConnectorState.RUNNING

    stop_inference_connectors(runners)

    assert instance.state == ConnectorState.STOPPED
    assert runner._thread is None


def test_stop_inference_connectors_handles_an_empty_dict():
    stop_inference_connectors({})  # must not raise


def test_a_stopped_connector_can_be_reconfigured_for_a_new_session():
    # The session-bound lifecycle depends on this: session A completes
    # (stop), then session B starts (configure+start again) using the
    # SAME instance - must not raise "already configured" or leak state
    # from session A.
    specs = [{'id': 'x', 'plugin': 'acme.inference.fake'}]
    connectors = build_inference_connector_instances(specs, _registry_with_fake_plugins())
    runners_a = start_inference_connectors('session-a', connectors)
    stop_inference_connectors(runners_a)

    runners_b = start_inference_connectors('session-b', connectors)
    try:
        instance, _runner = runners_b['x']
        assert instance.state == ConnectorState.RUNNING
        assert instance._plugin.configured_with['session_id'] == 'session-b'
    finally:
        stop_inference_connectors(runners_b)


# --- the direct regression test: a real row lands in the database ----------

def test_a_started_inference_connector_actually_polls_and_writes_to_the_database(tmp_path):
    """Before this wiring, an inference bridge PredictionConnector plugin
    would discover as AVAILABLE and sit inert forever, same class of gap
    BUG-003/#110 closed for poll_connectors and #111 closed for resource
    collectors. This builds a real connector from config
    (build_inference_connector_instances, then start_inference_connectors
    - exactly what api/sessions.py's start_session now calls), lets it
    run against a real temporary database for a couple of poll cycles,
    and confirms a prediction genuinely lands in the database."""
    db_path = tmp_path / 'test.db'
    conn = db_module.connect(str(db_path))
    try:
        repo.create_scenario(conn, Scenario(id='sc1', name='demo'))
        repo.create_session(conn, Session(
            id='s1', name='demo session', scenario_id='sc1', started_at=datetime.now(timezone.utc),
        ))
    finally:
        conn.close()

    def _prediction(pred_id: str) -> Prediction:
        return Prediction(
            id=pred_id, session_id='s1', timestamp_ms=100.0, source_id='acme.inference.fake',
            sensor_ids=['demo_rgb'], task='vehicle_presence', value={'label': 'present'}, confidence=0.9,
        )

    plugin = _FakeInferenceBridge()
    plugin.next_poll_result = [_prediction('pred-a')]
    registry = PluginRegistry()
    registry.records['acme.inference.fake'] = PluginRecord(
        plugin_id='acme.inference.fake', status=PluginStatus.AVAILABLE,
        descriptor=plugin.descriptor(), instance=plugin, factory=lambda: plugin, distribution_name='acme',
    )

    specs = [{'id': 'x', 'plugin': 'acme.inference.fake', 'poll_interval_s': 0.05}]
    connectors = build_inference_connector_instances(specs, registry)
    runners = start_inference_connectors('s1', connectors, connect=lambda: db_module.connect(str(db_path)))
    try:
        assert set(runners) == {'x'}
        time.sleep(0.3)  # let the background thread actually poll a few times
    finally:
        stop_inference_connectors(runners)

    conn = db_module.connect(str(db_path))
    try:
        stored = repo.list_predictions(conn, 's1')
    finally:
        conn.close()
    assert {p.id for p in stored} == {'pred-a'}  # genuinely persisted, not just "instance says RUNNING"
