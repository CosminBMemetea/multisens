"""Phase 97 (v0.9): the pull-based connector wrappers -
`PredictionConnectorInstance`/`GroundTruthConnectorInstance`. Lifecycle
enforcement mirrors Phase 95's own `ConnectorInstance` tests (not
repeated exhaustively here - same underlying pattern, proven once); this
file focuses on what's new: `poll()`'s empty-when-not-running behavior,
malformed-item filtering, and failure handling.
"""
import pytest
from app.plugins.connector_instance import ConnectorLifecycleError, ConnectorRuntimeError
from app.plugins.poll_connector_instance import GroundTruthConnectorInstance, PredictionConnectorInstance
from multisens_sdk import ConnectorConfigError, ConnectorHealth, ConnectorState, GroundTruth, Prediction


def _prediction(**overrides) -> Prediction:
    defaults = dict(
        id='pred-1', session_id='s1', timestamp_ms=1.0, source_id='acme-detector',
        sensor_ids=['robot_front_rgb'], task='obstacle_detection', value={'detections': []},
    )
    return Prediction(**{**defaults, **overrides})


def _ground_truth(**overrides) -> GroundTruth:
    defaults = dict(id='gt-1', session_id='s1', timestamp_ms=1.0, task='obstacle_detection', value={'objects': []})
    return GroundTruth(**{**defaults, **overrides})


class _FakePredictionPlugin:
    def __init__(self):
        self.configure_calls = 0
        self.start_calls = 0
        self.stop_calls = 0
        self.fail_configure = False
        self.fail_start = False
        self.next_poll_result: list = []
        self._running = False

    def descriptor(self):
        raise NotImplementedError

    def configure(self, config: dict) -> None:
        self.configure_calls += 1
        if self.fail_configure:
            raise ValueError('deliberately broken configure()')

    def start(self) -> None:
        self.start_calls += 1
        if self.fail_start:
            raise RuntimeError('deliberately broken start()')
        self._running = True

    def stop(self) -> None:
        self.stop_calls += 1
        self._running = False

    def health(self) -> ConnectorHealth:
        return ConnectorHealth(state=ConnectorState.RUNNING if self._running else ConnectorState.STOPPED)

    def poll(self) -> list:
        return self.next_poll_result


def _running_prediction_instance() -> tuple[PredictionConnectorInstance, _FakePredictionPlugin]:
    plugin = _FakePredictionPlugin()
    instance = PredictionConnectorInstance('acme.prediction.mock', plugin)
    instance.configure({})
    instance.start()
    return instance, plugin


# --- basic lifecycle (once per class, not exhaustively re-derived) --------

def test_prediction_connector_configure_invalid_raises_connector_config_error():
    plugin = _FakePredictionPlugin()
    plugin.fail_configure = True
    instance = PredictionConnectorInstance('acme.prediction.mock', plugin)
    with pytest.raises(ConnectorConfigError):
        instance.configure({})


def test_prediction_connector_start_before_configure_raises_lifecycle_error():
    instance = PredictionConnectorInstance('acme.prediction.mock', _FakePredictionPlugin())
    with pytest.raises(ConnectorLifecycleError):
        instance.start()


def test_prediction_connector_repeated_start_is_a_no_op():
    instance, plugin = _running_prediction_instance()
    instance.start()
    instance.start()
    assert plugin.start_calls == 1


def test_ground_truth_connector_basic_lifecycle_works_the_same_way():
    class _FakeGroundTruthPlugin(_FakePredictionPlugin):
        pass

    plugin = _FakeGroundTruthPlugin()
    instance = GroundTruthConnectorInstance('acme.groundtruth.mock', plugin)
    instance.configure({})
    instance.start()
    assert instance.state == ConnectorState.RUNNING
    instance.stop()
    assert instance.state == ConnectorState.STOPPED


# --- poll() ------------------------------------------------------------------

def test_poll_before_running_returns_empty_list_without_calling_the_plugin():
    plugin = _FakePredictionPlugin()
    instance = PredictionConnectorInstance('acme.prediction.mock', plugin)
    instance.configure({})
    assert instance.poll() == []


def test_poll_while_running_returns_valid_predictions():
    instance, plugin = _running_prediction_instance()
    plugin.next_poll_result = [_prediction(id='pred-a'), _prediction(id='pred-b')]
    result = instance.poll()
    assert [p.id for p in result] == ['pred-a', 'pred-b']


def test_poll_filters_out_malformed_non_prediction_items_keeping_the_valid_ones():
    instance, plugin = _running_prediction_instance()
    plugin.next_poll_result = [_prediction(id='pred-good'), {'not': 'a prediction'}, None, 'garbage']
    result = instance.poll()
    assert [p.id for p in result] == ['pred-good']


def test_poll_that_raises_moves_to_failed_and_returns_empty_not_a_crash():
    instance, plugin = _running_prediction_instance()

    def _explode():
        raise RuntimeError('poll() itself is broken')
    plugin.poll = _explode

    assert instance.poll() == []
    assert instance.state == ConnectorState.FAILED


# --- start()/stop()/health() failure (v0.9, Phase 105 robustness review -
# these three paths already existed in _PollConnectorInstance's own source
# since Phase 97, but had no dedicated test proving they actually move the
# connector to FAILED rather than propagating unguarded) --------------------

def test_prediction_connector_start_failure_raises_and_moves_to_failed():
    plugin = _FakePredictionPlugin()
    plugin.fail_start = True
    instance = PredictionConnectorInstance('acme.prediction.mock', plugin)
    instance.configure({})
    with pytest.raises(ConnectorRuntimeError):
        instance.start()
    assert instance.state == ConnectorState.FAILED


def test_prediction_connector_stop_failure_raises_and_moves_to_failed():
    instance, plugin = _running_prediction_instance()

    def _explode():
        raise RuntimeError('deliberately broken stop()')
    plugin.stop = _explode

    with pytest.raises(ConnectorRuntimeError):
        instance.stop()
    assert instance.state == ConnectorState.FAILED


def test_prediction_connector_health_call_that_raises_moves_to_failed_never_propagates():
    instance, plugin = _running_prediction_instance()

    def _explode():
        raise RuntimeError('deliberately broken health()')
    plugin.health = _explode

    health = instance.health()  # must not raise
    assert health.state == ConnectorState.FAILED
    assert 'deliberately broken health()' in health.message
    assert instance.state == ConnectorState.FAILED


def test_ground_truth_poll_filters_non_ground_truth_items():
    plugin = _FakePredictionPlugin()
    instance = GroundTruthConnectorInstance('acme.groundtruth.mock', plugin)
    instance.configure({})
    instance.start()
    plugin.next_poll_result = [_ground_truth(id='gt-good'), _prediction(id='pred-wrong-type')]
    result = instance.poll()
    assert [g.id for g in result] == ['gt-good']
