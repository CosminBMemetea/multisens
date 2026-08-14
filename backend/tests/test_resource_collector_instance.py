"""Phase 99 (v0.9): `ResourceCollectorInstance` lifecycle - mirrors Phase
95/97's own connector-wrapper tests (not exhaustively re-derived here,
same underlying pattern proven twice already); focuses on what's new:
`sample()`'s empty-when-not-running behavior and malformed-item
filtering for `ResourceObservation`.
"""
from datetime import datetime, timezone

import pytest
from app.plugins.connector_instance import ConnectorLifecycleError
from app.plugins.resource_collector_instance import ResourceCollectorInstance
from multisens_sdk import ConnectorConfigError, ConnectorHealth, ConnectorState, ResourceObservation


def _observation(**overrides) -> ResourceObservation:
    now = datetime.now(timezone.utc)
    defaults = dict(
        id='obs-1', session_id='s1', metric='synthetic_metric', value=42.0, unit='widgets',
        quality='measured', source='synthetic_metric_plugin', platform_id='test-platform',
        started_at=now, ended_at=now,
    )
    return ResourceObservation(**{**defaults, **overrides})


class _FakeResourceCollectorPlugin:
    def __init__(self):
        self.fail_configure = False
        self.next_sample_result: list = []
        self._running = False

    def descriptor(self):
        raise NotImplementedError

    def available_metrics(self):
        return []

    def configure(self, config: dict) -> None:
        if self.fail_configure:
            raise ValueError('deliberately broken configure()')

    def start(self) -> None:
        self._running = True

    def stop(self) -> None:
        self._running = False

    def health(self) -> ConnectorHealth:
        return ConnectorHealth(state=ConnectorState.RUNNING if self._running else ConnectorState.STOPPED)

    def sample(self) -> list:
        return self.next_sample_result


def _running_instance() -> tuple[ResourceCollectorInstance, _FakeResourceCollectorPlugin]:
    plugin = _FakeResourceCollectorPlugin()
    instance = ResourceCollectorInstance('acme.resource.mock', plugin)
    instance.configure({})
    instance.start()
    return instance, plugin


def test_configure_invalid_raises_connector_config_error():
    plugin = _FakeResourceCollectorPlugin()
    plugin.fail_configure = True
    instance = ResourceCollectorInstance('acme.resource.mock', plugin)
    with pytest.raises(ConnectorConfigError):
        instance.configure({})


def test_start_before_configure_raises_lifecycle_error():
    instance = ResourceCollectorInstance('acme.resource.mock', _FakeResourceCollectorPlugin())
    with pytest.raises(ConnectorLifecycleError):
        instance.start()


def test_sample_before_running_returns_empty_list_without_calling_the_plugin():
    plugin = _FakeResourceCollectorPlugin()
    instance = ResourceCollectorInstance('acme.resource.mock', plugin)
    instance.configure({})
    assert instance.sample() == []


def test_sample_while_running_returns_valid_observations():
    instance, plugin = _running_instance()
    plugin.next_sample_result = [_observation(id='obs-a'), _observation(id='obs-b')]
    result = instance.sample()
    assert [o.id for o in result] == ['obs-a', 'obs-b']


def test_sample_filters_out_malformed_non_observation_items():
    instance, plugin = _running_instance()
    plugin.next_sample_result = [_observation(id='obs-good'), {'not': 'an observation'}, None]
    result = instance.sample()
    assert [o.id for o in result] == ['obs-good']


def test_sample_that_raises_moves_to_failed_and_returns_empty_not_a_crash():
    instance, plugin = _running_instance()

    def _explode():
        raise RuntimeError('sample() itself is broken')
    plugin.sample = _explode

    assert instance.sample() == []
    assert instance.state == ConnectorState.FAILED


def test_stop_then_repeated_stop_is_a_no_op():
    instance, plugin = _running_instance()
    instance.stop()
    instance.stop()
    assert instance.state == ConnectorState.STOPPED
