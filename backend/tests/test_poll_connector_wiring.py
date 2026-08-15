"""v0.9 bug hunt (BUG-003, issue #110): `build_poll_runners()`/
`stop_poll_runners()` - the config-driven wiring that closes a real gap
`PollRunner`/`PredictionConnectorInstance`/`GroundTruthConnectorInstance`
(Phase 97) never had: nothing in the running application ever
constructed one, so an installed prediction/ground-truth plugin would
discover as `AVAILABLE` and then sit inert forever, never polling
anything. Mirrors `test_plugin_manager.py`'s own style for
`build_connector_instances()`/`stop_connector_instances()`.

`test_a_registered_prediction_plugin_actually_polls_and_writes_to_the_database`
below is the direct regression test for the bug itself - it fails
against the pre-fix code (nothing would ever call `runner.start()`) and
passes now.
"""
import time
from datetime import datetime, timezone

from app.config import load_poll_connectors
from app.domain.models import Scenario, Session
from app.persistence import db as db_module
from app.persistence import repository as repo
from app.plugins.manager import build_poll_runners, stop_poll_runners
from app.plugins.registry import PluginRecord, PluginRegistry, PluginStatus
from multisens_sdk import (
    MULTISENS_PLUGIN_API_VERSION,
    ConnectorConfigError,
    ConnectorHealth,
    ConnectorState,
    GroundTruth,
    PluginDescriptor,
    PluginType,
    Prediction,
)


def _prediction(pred_id: str) -> Prediction:
    return Prediction(
        id=pred_id, session_id='s1', timestamp_ms=100.0, source_id='acme-detector',
        sensor_ids=['robot_front_rgb'], task='obstacle_detection', value={'detections': []},
    )


def _ground_truth(gt_id: str) -> GroundTruth:
    return GroundTruth(id=gt_id, session_id='s1', timestamp_ms=100.0, task='obstacle_detection', value={'objects': []})


class _FakePredictionConnector:
    def __init__(self):
        self.configured_with: dict | None = None
        self.started = False
        self.next_poll_result: list = []
        self.fail_configure = False

    def descriptor(self) -> PluginDescriptor:
        return PluginDescriptor(
            plugin_id='acme.prediction.fake', name='Fake Prediction Connector', version='1.0.0',
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

    def poll(self) -> list:
        return self.next_poll_result


class _FakeGroundTruthConnector(_FakePredictionConnector):
    def descriptor(self) -> PluginDescriptor:
        return PluginDescriptor(
            plugin_id='acme.groundtruth.fake', name='Fake GroundTruth Connector', version='1.0.0',
            plugin_type=PluginType.GROUND_TRUTH_CONNECTOR, api_version=MULTISENS_PLUGIN_API_VERSION,
        )


class _FakeEvaluatorPlugin:
    """Stands in for a plugin of the WRONG type, to prove
    build_poll_runners() rejects it rather than silently polling
    something that was never a poll connector."""
    def descriptor(self) -> PluginDescriptor:
        return PluginDescriptor(
            plugin_id='acme.evaluator.fake', name='Fake Evaluator', version='1.0.0',
            plugin_type=PluginType.EVALUATOR, api_version=MULTISENS_PLUGIN_API_VERSION,
        )


def _registry_with_fake_plugins() -> PluginRegistry:
    registry = PluginRegistry()
    prediction_plugin = _FakePredictionConnector()
    registry.records['acme.prediction.fake'] = PluginRecord(
        plugin_id='acme.prediction.fake', status=PluginStatus.AVAILABLE,
        descriptor=prediction_plugin.descriptor(), instance=prediction_plugin,
        factory=lambda: _FakePredictionConnector(), distribution_name='acme',
    )
    gt_plugin = _FakeGroundTruthConnector()
    registry.records['acme.groundtruth.fake'] = PluginRecord(
        plugin_id='acme.groundtruth.fake', status=PluginStatus.AVAILABLE,
        descriptor=gt_plugin.descriptor(), instance=gt_plugin,
        factory=lambda: _FakeGroundTruthConnector(), distribution_name='acme',
    )
    evaluator_plugin = _FakeEvaluatorPlugin()
    registry.records['acme.evaluator.fake'] = PluginRecord(
        plugin_id='acme.evaluator.fake', status=PluginStatus.AVAILABLE,
        descriptor=evaluator_plugin.descriptor(), instance=evaluator_plugin,
        factory=lambda: _FakeEvaluatorPlugin(), distribution_name='acme',
    )
    return registry


# --- config-entry validation --------------------------------------------------

def test_entry_missing_id_or_plugin_is_skipped_not_a_crash():
    specs = [{'plugin': 'acme.prediction.fake'}, {'id': 'no-plugin-named'}]
    runners = build_poll_runners(specs, _registry_with_fake_plugins())
    assert runners == {}


def test_unknown_plugin_is_skipped_not_a_crash():
    specs = [{'id': 'x', 'plugin': 'does.not.exist'}]
    runners = build_poll_runners(specs, _registry_with_fake_plugins())
    assert runners == {}


def test_wrong_typed_plugin_is_skipped_not_a_crash():
    specs = [{'id': 'x', 'plugin': 'acme.evaluator.fake'}]
    runners = build_poll_runners(specs, _registry_with_fake_plugins())
    assert runners == {}


def test_invalid_poll_interval_is_skipped(monkeypatch):
    for bad_interval in (-1, 0, float('nan'), 'not-a-number', True):
        specs = [{'id': 'x', 'plugin': 'acme.prediction.fake', 'poll_interval_s': bad_interval}]
        runners = build_poll_runners(specs, _registry_with_fake_plugins())
        assert runners == {}, f'poll_interval_s={bad_interval!r} should have been rejected'


def test_configure_failure_drops_the_entry_entirely():
    # factory() builds a fresh object each call - fail_configure has to
    # be baked into the factory closure itself, not set on some other
    # already-constructed instance, which would never be the one
    # build_poll_runners() actually uses.
    registry = _registry_with_fake_plugins()
    registry.records['acme.prediction.fake'] = PluginRecord(
        plugin_id='acme.prediction.fake', status=PluginStatus.AVAILABLE,
        descriptor=_FakePredictionConnector().descriptor(),
        instance=None, distribution_name='acme',
        factory=_failing_prediction_connector,
    )
    specs = [{'id': 'x', 'plugin': 'acme.prediction.fake'}]
    runners = build_poll_runners(specs, registry)
    assert runners == {}


def _failing_prediction_connector() -> _FakePredictionConnector:
    connector = _FakePredictionConnector()
    connector.fail_configure = True
    return connector


# --- successful wiring ---------------------------------------------------------

def test_valid_prediction_connector_is_built_configured_and_started():
    specs = [{'id': 'acme-predictions', 'plugin': 'acme.prediction.fake', 'config': {'endpoint': 'https://x'}}]
    runners = build_poll_runners(specs, _registry_with_fake_plugins())
    try:
        assert set(runners) == {'acme-predictions'}
        instance, runner = runners['acme-predictions']
        assert instance.state == ConnectorState.RUNNING
        assert instance._plugin.configured_with == {'endpoint': 'https://x'}
    finally:
        stop_poll_runners(runners)


def test_valid_ground_truth_connector_is_built_configured_and_started():
    specs = [{'id': 'acme-gt', 'plugin': 'acme.groundtruth.fake'}]
    runners = build_poll_runners(specs, _registry_with_fake_plugins())
    try:
        assert set(runners) == {'acme-gt'}
        instance, _runner = runners['acme-gt']
        assert instance.state == ConnectorState.RUNNING
    finally:
        stop_poll_runners(runners)


def test_two_poll_connectors_stay_independent():
    specs = [
        {'id': 'acme-predictions', 'plugin': 'acme.prediction.fake'},
        {'id': 'acme-gt', 'plugin': 'acme.groundtruth.fake'},
    ]
    runners = build_poll_runners(specs, _registry_with_fake_plugins())
    try:
        assert set(runners) == {'acme-predictions', 'acme-gt'}
        pred_instance, _ = runners['acme-predictions']
        gt_instance, _ = runners['acme-gt']
        assert pred_instance is not gt_instance
        assert pred_instance._plugin is not gt_instance._plugin
    finally:
        stop_poll_runners(runners)


def test_stop_poll_runners_stops_both_the_thread_and_the_connector():
    specs = [{'id': 'acme-predictions', 'plugin': 'acme.prediction.fake'}]
    runners = build_poll_runners(specs, _registry_with_fake_plugins())
    instance, runner = runners['acme-predictions']
    assert instance.state == ConnectorState.RUNNING

    stop_poll_runners(runners)

    assert instance.state == ConnectorState.STOPPED
    assert runner._thread is None  # the background thread genuinely stopped


def test_stop_poll_runners_handles_an_empty_dict():
    stop_poll_runners({})  # must not raise


# --- the actual regression test for the bug ------------------------------------

def test_a_registered_prediction_plugin_actually_polls_and_writes_to_the_database(tmp_path):
    """The direct regression test for BUG-003: before this fix, nothing
    in the application ever called PollRunner.start() for a discovered
    prediction/ground-truth plugin - it would sit AVAILABLE forever and
    never ingest a row. This builds a real poll runner from config
    (build_poll_runners, exactly what main.py's lifespan now calls),
    lets it run against a real temporary database for a couple of poll
    cycles, and confirms a prediction genuinely lands in the database -
    not just that the connector object reports RUNNING."""
    db_path = tmp_path / 'test.db'
    conn = db_module.connect(str(db_path))
    try:
        repo.create_scenario(conn, Scenario(id='sc1', name='demo'))
        repo.create_session(conn, Session(
            id='s1', name='demo session', scenario_id='sc1', started_at=datetime.now(timezone.utc),
        ))
    finally:
        conn.close()

    # build_poll_runners() always builds a *fresh* object via record.factory()
    # (never record.instance, which is only the registry's own discovery-time
    # bookkeeping instance) - so the pre-configured poll() output has to be
    # baked into the factory closure itself, same reasoning as
    # test_configure_failure_drops_the_entry_entirely above.
    plugin = _FakePredictionConnector()
    plugin.next_poll_result = [_prediction('pred-a')]
    registry = PluginRegistry()
    registry.records['acme.prediction.fake'] = PluginRecord(
        plugin_id='acme.prediction.fake', status=PluginStatus.AVAILABLE,
        descriptor=plugin.descriptor(), instance=plugin, factory=lambda: plugin, distribution_name='acme',
    )

    specs = [{'id': 'acme-predictions', 'plugin': 'acme.prediction.fake', 'poll_interval_s': 0.05}]
    runners = build_poll_runners(specs, registry, connect=lambda: db_module.connect(str(db_path)))
    try:
        assert set(runners) == {'acme-predictions'}
        time.sleep(0.3)  # let the background thread actually poll a few times
    finally:
        stop_poll_runners(runners)

    conn = db_module.connect(str(db_path))
    try:
        stored = repo.list_predictions(conn, 's1')
    finally:
        conn.close()
    assert {p.id for p in stored} == {'pred-a'}  # genuinely ingested, not just "connector says RUNNING"


def test_a_registered_ground_truth_plugin_actually_polls_and_writes_to_the_database(tmp_path):
    db_path = tmp_path / 'test.db'
    conn = db_module.connect(str(db_path))
    try:
        repo.create_scenario(conn, Scenario(id='sc1', name='demo'))
        repo.create_session(conn, Session(
            id='s1', name='demo session', scenario_id='sc1', started_at=datetime.now(timezone.utc),
        ))
    finally:
        conn.close()

    plugin = _FakeGroundTruthConnector()
    plugin.next_poll_result = [_ground_truth('gt-a')]
    registry = PluginRegistry()
    registry.records['acme.groundtruth.fake'] = PluginRecord(
        plugin_id='acme.groundtruth.fake', status=PluginStatus.AVAILABLE,
        descriptor=plugin.descriptor(), instance=plugin, factory=lambda: plugin, distribution_name='acme',
    )

    specs = [{'id': 'acme-gt', 'plugin': 'acme.groundtruth.fake', 'poll_interval_s': 0.05}]
    runners = build_poll_runners(specs, registry, connect=lambda: db_module.connect(str(db_path)))
    try:
        assert set(runners) == {'acme-gt'}
        time.sleep(0.3)
    finally:
        stop_poll_runners(runners)

    conn = db_module.connect(str(db_path))
    try:
        stored = repo.list_ground_truth(conn, 's1')
    finally:
        conn.close()
    assert {g.id for g in stored} == {'gt-a'}
