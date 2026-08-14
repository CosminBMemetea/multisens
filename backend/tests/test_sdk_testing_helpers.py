"""Phase 100 (v0.9): `multisens_sdk.testing`'s own contract-test helpers,
proven correct before any external plugin author relies on them - every
helper is exercised against both a passing fake and a deliberately-broken
one (issue #101's own acceptance bar).

Run from `backend/tests/` for practical reasons (the same pytest/Docker
setup every other test in this repository already uses), but these tests
exercise `multisens_sdk.testing` exclusively - nothing backend-internal.
"""
import pytest
from multisens_sdk import (
    MULTISENS_PLUGIN_API_VERSION,
    ConnectorHealth,
    ConnectorState,
    EvaluatorOutput,
    MetricDescriptor,
    PluginDescriptor,
    PluginType,
    ResourceObservation,
)
from multisens_sdk.testing import (
    assert_connector_lifecycle,
    assert_evaluator_deterministic,
    assert_evaluator_output_shape,
    assert_health_contract,
    assert_metric_descriptors_valid,
    assert_resource_observation_shape,
    assert_valid_plugin_descriptor,
)


def _valid_descriptor(**overrides) -> PluginDescriptor:
    defaults = dict(
        plugin_id='acme.sensor.mock', name='Mock Sensor', version='0.1.0',
        plugin_type=PluginType.SENSOR_CONNECTOR, api_version=MULTISENS_PLUGIN_API_VERSION,
        author='Acme', license='Apache-2.0',
    )
    return PluginDescriptor(**{**defaults, **overrides})


# --- assert_valid_plugin_descriptor -----------------------------------------

def test_assert_valid_plugin_descriptor_passes_a_well_formed_descriptor():
    assert_valid_plugin_descriptor(_valid_descriptor())  # must not raise


@pytest.mark.parametrize('overrides,expected_message', [
    ({'plugin_id': ''}, 'plugin_id must not be empty'),
    ({'plugin_id': 'nodot'}, 'dot-separated segments'),
    ({'plugin_id': 'Acme.Sensor.Mock'}, 'lowercase'),
    ({'plugin_id': 'acme.sensor mock'}, '[a-z0-9_.-]'),
    ({'name': ''}, 'name must not be empty'),
    ({'version': ''}, 'version must not be empty'),
    ({'api_version': ''}, 'api_version must not be empty'),
    ({'author': ''}, 'author must not be empty'),
    ({'license': ''}, 'license must not be empty'),
])
def test_assert_valid_plugin_descriptor_catches_each_broken_field(overrides, expected_message):
    with pytest.raises(AssertionError, match=expected_message):
        assert_valid_plugin_descriptor(_valid_descriptor(**overrides))


def test_assert_valid_plugin_descriptor_rejects_a_non_descriptor():
    with pytest.raises(AssertionError, match='expected a PluginDescriptor'):
        assert_valid_plugin_descriptor({'plugin_id': 'acme.sensor.mock'})  # a plain dict, not the real type


# --- assert_health_contract --------------------------------------------------

def test_assert_health_contract_passes_a_well_formed_health():
    assert_health_contract(ConnectorHealth(state=ConnectorState.RUNNING, last_sample_age_s=0.5, message='ok'))


def test_assert_health_contract_catches_a_negative_sample_age():
    with pytest.raises(AssertionError, match='last_sample_age_s'):
        assert_health_contract(ConnectorHealth(state=ConnectorState.RUNNING, last_sample_age_s=-1.0))


def test_assert_health_contract_catches_a_non_connector_state():
    # A real ConnectorHealth (frozen dataclasses don't enforce field
    # types at runtime), but `state` is a plain string rather than a
    # genuine ConnectorState member - a real plugin bug (e.g. returning
    # "running" instead of ConnectorState.RUNNING) this helper must
    # catch.
    broken_health = ConnectorHealth(state='running')  # type: ignore[arg-type]
    with pytest.raises(AssertionError, match='ConnectorState'):
        assert_health_contract(broken_health)


# --- assert_connector_lifecycle ----------------------------------------------

class _GoodConnector:
    def __init__(self):
        self._running = False

    def configure(self, config: dict) -> None:
        pass

    def start(self) -> None:
        self._running = True

    def stop(self) -> None:
        self._running = False

    def health(self) -> ConnectorHealth:
        return ConnectorHealth(state=ConnectorState.RUNNING if self._running else ConnectorState.STOPPED)


def test_assert_connector_lifecycle_passes_a_well_behaved_connector():
    connector = _GoodConnector()
    assert_connector_lifecycle(connector, configure=lambda: connector.configure({}))


class _BrokenConnector(_GoodConnector):
    def health(self) -> ConnectorHealth:
        # Never transitions to RUNNING/STARTING/DEGRADED after start() -
        # a real plugin bug this helper is meant to catch.
        return ConnectorHealth(state=ConnectorState.STOPPED)


def test_assert_connector_lifecycle_catches_a_connector_that_never_reports_running():
    connector = _BrokenConnector()
    with pytest.raises(AssertionError, match='expected RUNNING, STARTING, or DEGRADED'):
        assert_connector_lifecycle(connector, configure=lambda: connector.configure({}))


class _BadHealthShapeConnector(_GoodConnector):
    def health(self):
        return {'state': 'running'}  # not a real ConnectorHealth at all


def test_assert_connector_lifecycle_catches_a_malformed_health_return_value():
    connector = _BadHealthShapeConnector()
    with pytest.raises(AssertionError, match='expected a ConnectorHealth'):
        assert_connector_lifecycle(connector, configure=lambda: connector.configure({}))


# --- assert_metric_descriptors_valid -----------------------------------------

def test_assert_metric_descriptors_valid_passes_well_formed_descriptors():
    assert_metric_descriptors_valid([
        MetricDescriptor(id='precision', higher_is_better=True),
        MetricDescriptor(id='bias', higher_is_better=None),
    ])


def test_assert_metric_descriptors_valid_catches_a_duplicate_id():
    with pytest.raises(AssertionError, match='duplicate metric id'):
        assert_metric_descriptors_valid([
            MetricDescriptor(id='precision'), MetricDescriptor(id='precision'),
        ])


def test_assert_metric_descriptors_valid_catches_an_empty_id():
    with pytest.raises(AssertionError, match='id must not be empty'):
        assert_metric_descriptors_valid([MetricDescriptor(id='')])


# --- assert_evaluator_output_shape -------------------------------------------

def test_assert_evaluator_output_shape_passes_a_well_formed_output():
    assert_evaluator_output_shape(EvaluatorOutput(
        sample_count=10, matched_samples=8, unmatched_predictions=1, unmatched_ground_truth=1,
        metrics={'accuracy': 0.8, 'undefined_metric': None},
    ))


def test_assert_evaluator_output_shape_catches_a_negative_count():
    with pytest.raises(AssertionError, match='sample_count'):
        assert_evaluator_output_shape(EvaluatorOutput(
            sample_count=-1, matched_samples=0, unmatched_predictions=0, unmatched_ground_truth=0, metrics={},
        ))


def test_assert_evaluator_output_shape_catches_a_fabricated_string_metric():
    with pytest.raises(AssertionError, match="metrics\\['accuracy'\\]"):
        assert_evaluator_output_shape(EvaluatorOutput(
            sample_count=1, matched_samples=1, unmatched_predictions=0, unmatched_ground_truth=0,
            metrics={'accuracy': 'high'},  # never a fabricated non-numeric placeholder
        ))


# --- assert_evaluator_deterministic ------------------------------------------

def test_assert_evaluator_deterministic_passes_a_pure_function():
    def _evaluate() -> EvaluatorOutput:
        return EvaluatorOutput(sample_count=1, matched_samples=1, unmatched_predictions=0,
                                unmatched_ground_truth=0, metrics={'accuracy': 1.0})
    assert_evaluator_deterministic(_evaluate)


def test_assert_evaluator_deterministic_catches_nondeterminism():
    call_count = {'n': 0}

    def _evaluate() -> EvaluatorOutput:
        call_count['n'] += 1
        return EvaluatorOutput(sample_count=1, matched_samples=1, unmatched_predictions=0,
                                unmatched_ground_truth=0, metrics={'accuracy': float(call_count['n'])})

    with pytest.raises(AssertionError, match='different metrics'):
        assert_evaluator_deterministic(_evaluate)


# --- assert_resource_observation_shape ---------------------------------------

def _observation(**overrides) -> ResourceObservation:
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    defaults = dict(id='obs-1', session_id='s1', metric='synthetic_metric', value=1.0, unit='widgets',
                     quality='measured', source='test-plugin', platform_id='test-platform',
                     started_at=now, ended_at=now)
    return ResourceObservation(**{**defaults, **overrides})


def test_assert_resource_observation_shape_passes_a_well_formed_measured_observation():
    assert_resource_observation_shape(_observation())


def test_assert_resource_observation_shape_passes_a_well_formed_unavailable_observation():
    assert_resource_observation_shape(_observation(value=None, quality='unavailable'))


def test_assert_resource_observation_shape_catches_a_non_observation():
    with pytest.raises(AssertionError, match='expected a ResourceObservation'):
        assert_resource_observation_shape({'metric': 'synthetic_metric', 'value': 1.0})
