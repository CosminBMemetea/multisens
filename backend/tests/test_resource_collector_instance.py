"""Phase 99 (v0.9): `ResourceCollectorInstance` lifecycle - mirrors Phase
95/97's own connector-wrapper tests (not exhaustively re-derived here,
same underlying pattern proven twice already); focuses on what's new:
`sample()`'s empty-when-not-running behavior and malformed-item
filtering for `ResourceObservation`.
"""
from datetime import datetime, timezone

import pytest
from app.plugins.connector_instance import ConnectorLifecycleError, ConnectorRuntimeError
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
        self.fail_start = False
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
        if self.fail_start:
            raise RuntimeError('deliberately broken start()')
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


def test_sample_that_raises_moves_to_degraded_and_returns_empty_not_a_crash():
    instance, plugin = _running_instance()

    def _explode():
        raise RuntimeError('sample() itself is broken')
    plugin.sample = _explode

    assert instance.sample() == []
    assert instance.state == ConnectorState.DEGRADED


def test_sample_self_heals_back_to_running_once_the_plugin_recovers():
    # v1.0-RC issue #126: a transient collector failure must not
    # permanently end this session's resource observations - the next
    # poll cycle must keep trying, and a successful call must flip
    # straight back to RUNNING.
    instance, plugin = _running_instance()

    def _explode():
        raise RuntimeError('sample() itself is broken')
    plugin.sample = _explode
    instance.sample()
    assert instance.state == ConnectorState.DEGRADED

    plugin.sample = lambda: [_observation(id='obs-recovered')]
    result = instance.sample()

    assert [o.id for o in result] == ['obs-recovered']
    assert instance.state == ConnectorState.RUNNING


def test_stop_then_repeated_stop_is_a_no_op():
    instance, plugin = _running_instance()
    instance.stop()
    instance.stop()
    assert instance.state == ConnectorState.STOPPED


# --- start()/stop()/health() failure (v0.9, Phase 105 robustness review -
# these three paths already existed in ResourceCollectorInstance's own
# source since Phase 99, but had no dedicated test proving they actually
# move the connector to FAILED rather than propagating unguarded) ----------

def test_start_failure_raises_and_moves_to_failed():
    plugin = _FakeResourceCollectorPlugin()
    plugin.fail_start = True
    instance = ResourceCollectorInstance('acme.resource.mock', plugin)
    instance.configure({})
    with pytest.raises(ConnectorRuntimeError):
        instance.start()
    assert instance.state == ConnectorState.FAILED


def test_stop_failure_raises_and_moves_to_failed():
    instance, plugin = _running_instance()

    def _explode():
        raise RuntimeError('deliberately broken stop()')
    plugin.stop = _explode

    with pytest.raises(ConnectorRuntimeError):
        instance.stop()
    assert instance.state == ConnectorState.FAILED


def test_health_call_that_raises_moves_to_degraded_never_propagates():
    instance, plugin = _running_instance()

    def _explode():
        raise RuntimeError('deliberately broken health()')
    plugin.health = _explode

    health = instance.health()  # must not raise
    assert health.state == ConnectorState.DEGRADED
    assert 'deliberately broken health()' in health.message
    assert instance.state == ConnectorState.DEGRADED


def test_health_self_heals_back_to_running_once_the_plugin_recovers():
    instance, plugin = _running_instance()

    def _explode():
        raise RuntimeError('deliberately broken health()')
    plugin.health = _explode
    instance.health()
    assert instance.state == ConnectorState.DEGRADED

    plugin.health = lambda: ConnectorHealth(state=ConnectorState.RUNNING)
    health = instance.health()

    assert health.state == ConnectorState.RUNNING
    assert instance.state == ConnectorState.RUNNING  # the wrapper's own tracked state, not just the returned value


def test_health_adopts_a_plugin_reported_degraded_state_without_the_call_raising():
    # v1.0-RC issue #126 (found live-verifying its own fix): a plugin can
    # legitimately self-report DEGRADED via a normal, non-raising
    # ConnectorHealth return - the wrapper must not blindly force
    # RUNNING just because the health() call itself didn't raise.
    instance, plugin = _running_instance()
    plugin.health = lambda: ConnectorHealth(state=ConnectorState.DEGRADED, message='collector degraded')

    health = instance.health()

    assert health.state == ConnectorState.DEGRADED
    assert instance.state == ConnectorState.DEGRADED
