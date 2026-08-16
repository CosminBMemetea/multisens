"""Phase 95 (v0.9): the generic `ConnectorInstance` lifecycle wrapper -
configuration, invalid configuration, start, repeated start, health,
sample, stop, repeated stop, runtime failure, and two sensor instances
sharing one connector implementation (same discipline as issue #91's own
robustness-test precedent: one dedicated test per bullet).
"""
import pytest
from app.plugins.connector_instance import (
    MAX_SAMPLE_PAYLOAD_BYTES,
    ConnectorInstance,
    ConnectorLifecycleError,
    ConnectorRuntimeError,
)
from multisens_sdk import ConnectorConfigError, ConnectorHealth, ConnectorState, SensorSample


class _FakeConnector:
    """A controllable SensorConnector test double - each lifecycle
    method can be told to fail on demand, and every call is counted so
    tests can assert exactly how many times the underlying plugin code
    actually ran."""
    def __init__(self):
        self.configure_calls = 0
        self.start_calls = 0
        self.stop_calls = 0
        self.sample_calls = 0
        self.health_calls = 0
        self.configured_with: tuple[str, dict] | None = None
        self.fail_configure = False
        self.fail_start = False
        self.fail_stop = False
        self.fail_sample = False
        self.fail_health = False
        self.next_sample: SensorSample | None = None
        self._running = False

    def descriptor(self):
        raise NotImplementedError('not needed for these lifecycle tests')

    def configure(self, sensor_id: str, config: dict) -> None:
        self.configure_calls += 1
        if self.fail_configure:
            raise ValueError('deliberately broken configure()')
        self.configured_with = (sensor_id, config)

    def start(self) -> None:
        self.start_calls += 1
        if self.fail_start:
            raise RuntimeError('deliberately broken start()')
        self._running = True

    def stop(self) -> None:
        self.stop_calls += 1
        if self.fail_stop:
            raise RuntimeError('deliberately broken stop()')
        self._running = False

    def health(self) -> ConnectorHealth:
        self.health_calls += 1
        if self.fail_health:
            raise RuntimeError('deliberately broken health()')
        return ConnectorHealth(state=ConnectorState.RUNNING if self._running else ConnectorState.STOPPED)

    def sample(self) -> SensorSample | None:
        self.sample_calls += 1
        if self.fail_sample:
            raise RuntimeError('deliberately broken sample()')
        return self.next_sample


def _configured_instance(fake: _FakeConnector | None = None) -> tuple[ConnectorInstance, _FakeConnector]:
    fake = fake or _FakeConnector()
    instance = ConnectorInstance(sensor_id='robot_front_rgb', plugin_id='acme.sensor.mock', connector=fake)
    instance.configure({'uri': 'rtsp://example/robot_front_rgb'})
    return instance, fake


# --- configuration ------------------------------------------------------

def test_configure_succeeds_and_forwards_sensor_id_and_config():
    instance, fake = _configured_instance()
    assert fake.configured_with == ('robot_front_rgb', {'uri': 'rtsp://example/robot_front_rgb'})
    assert instance.state == ConnectorState.STOPPED  # configure alone never starts anything


def test_configure_resolves_env_secret_refs_before_reaching_the_plugin(monkeypatch):
    monkeypatch.setenv('CAM_PASSWORD', 'hunter2')
    fake = _FakeConnector()
    instance = ConnectorInstance('robot_front_rgb', 'acme.sensor.mock', fake)
    instance.configure({'uri': 'rtsp://example', 'password_env': 'CAM_PASSWORD'})
    assert fake.configured_with == ('robot_front_rgb', {'uri': 'rtsp://example', 'password': 'hunter2'})


# --- invalid configuration ------------------------------------------------

def test_invalid_configuration_raises_connector_config_error_and_never_marks_configured():
    fake = _FakeConnector()
    fake.fail_configure = True
    instance = ConnectorInstance('robot_front_rgb', 'acme.sensor.mock', fake)
    with pytest.raises(ConnectorConfigError):
        instance.configure({})
    with pytest.raises(ConnectorLifecycleError, match='before configure'):
        instance.start()


def test_configure_while_running_raises_lifecycle_error_not_reconfigured_silently():
    instance, fake = _configured_instance()
    instance.start()
    with pytest.raises(ConnectorLifecycleError, match='RUNNING'):
        instance.configure({'uri': 'rtsp://different'})
    # The original configuration is untouched.
    assert fake.configured_with == ('robot_front_rgb', {'uri': 'rtsp://example/robot_front_rgb'})


# --- start / repeated start -----------------------------------------------

def test_start_transitions_to_running():
    instance, fake = _configured_instance()
    instance.start()
    assert instance.state == ConnectorState.RUNNING
    assert fake.start_calls == 1


def test_repeated_start_while_running_is_a_no_op():
    instance, fake = _configured_instance()
    instance.start()
    instance.start()
    instance.start()
    assert fake.start_calls == 1  # the plugin's own start() only ever ran once
    assert instance.state == ConnectorState.RUNNING


def test_start_after_failure_retries_rather_than_staying_stuck():
    fake = _FakeConnector()
    fake.fail_start = True
    instance = ConnectorInstance('robot_front_rgb', 'acme.sensor.mock', fake)
    instance.configure({})
    with pytest.raises(ConnectorRuntimeError):
        instance.start()
    assert instance.state == ConnectorState.FAILED

    fake.fail_start = False  # e.g. operator fixed the network/config
    instance.start()
    assert instance.state == ConnectorState.RUNNING
    assert fake.start_calls == 2


# --- health ----------------------------------------------------------------

def test_health_before_start_reports_stopped_without_calling_the_plugin():
    instance, fake = _configured_instance()
    health = instance.health()
    assert health.state == ConnectorState.STOPPED
    assert fake.health_calls == 0  # never delegated to the plugin - not RUNNING, nothing to ask it


def test_health_while_running_delegates_to_the_plugin():
    instance, fake = _configured_instance()
    instance.start()
    health = instance.health()
    assert health.state == ConnectorState.RUNNING


def test_health_call_that_raises_moves_the_connector_to_degraded_never_propagates():
    class _HealthExplodes(_FakeConnector):
        def health(self):
            raise RuntimeError('health() itself is broken')

    fake = _HealthExplodes()
    instance = ConnectorInstance('robot_front_rgb', 'acme.sensor.mock', fake)
    instance.configure({})
    instance.start()

    health = instance.health()  # must not raise
    assert health.state == ConnectorState.DEGRADED
    assert 'health() itself is broken' in health.message
    assert instance.state == ConnectorState.DEGRADED


def test_health_self_heals_back_to_running_once_the_plugin_recovers():
    # v1.0-RC issue #126: a transient RTSP hiccup must not permanently end
    # this connector's own health()/sample() reporting for the rest of
    # the session - the ROS ingestion side of the same sensor already
    # reconnects on its own; this wrapper must keep pace, not require a
    # full stop()+configure()+start() cycle to notice recovery.
    instance, fake = _configured_instance()
    instance.start()
    fake.fail_health = True
    instance.health()
    assert instance.state == ConnectorState.DEGRADED

    fake.fail_health = False
    health = instance.health()

    assert health.state == ConnectorState.RUNNING
    assert instance.state == ConnectorState.RUNNING


def test_health_adopts_a_plugin_reported_degraded_state_without_the_call_raising():
    # v1.0-RC issue #126 (found live-verifying its own fix): a plugin can
    # legitimately self-report DEGRADED via a normal, non-raising
    # ConnectorHealth return (e.g. builtin_rtsp.py's own connectivity
    # check) - the wrapper must not blindly force RUNNING just because
    # the health() call itself didn't raise.
    instance, fake = _configured_instance()
    instance.start()
    fake.health = lambda: ConnectorHealth(state=ConnectorState.DEGRADED, message='RTSP source unreachable')

    health = instance.health()

    assert health.state == ConnectorState.DEGRADED
    assert instance.state == ConnectorState.DEGRADED


# --- sample ------------------------------------------------------------------

def test_sample_before_running_returns_none_without_calling_the_plugin():
    instance, fake = _configured_instance()
    assert instance.sample() is None
    assert fake.sample_calls == 0


def test_sample_while_running_returns_the_plugins_own_sample():
    instance, fake = _configured_instance()
    instance.start()
    fake.next_sample = SensorSample(sensor_id='robot_front_rgb', timestamp_ms=1.0, sequence_id=1,
                                     data_type='scalar', payload={'value': 42})
    result = instance.sample()
    assert result is not None
    assert result.payload == {'value': 42}


def test_sample_that_raises_moves_to_degraded_and_returns_none_not_a_crash():
    instance, fake = _configured_instance()
    instance.start()
    fake.fail_sample = True
    assert instance.sample() is None
    assert instance.state == ConnectorState.DEGRADED


def test_sample_self_heals_back_to_running_once_the_plugin_recovers():
    instance, fake = _configured_instance()
    instance.start()
    fake.fail_sample = True
    instance.sample()
    assert instance.state == ConnectorState.DEGRADED

    fake.fail_sample = False
    fake.next_sample = SensorSample(sensor_id='robot_front_rgb', timestamp_ms=1.0, sequence_id=1,
                                     data_type='scalar', payload={'value': 1})
    result = instance.sample()

    assert result is not None
    assert instance.state == ConnectorState.RUNNING


def test_oversized_sample_payload_is_discarded_but_connector_stays_running():
    instance, fake = _configured_instance()
    instance.start()
    fake.next_sample = SensorSample(sensor_id='robot_front_rgb', timestamp_ms=1.0, sequence_id=1,
                                     data_type='scalar', payload={'blob': 'x' * (MAX_SAMPLE_PAYLOAD_BYTES + 1)})
    assert instance.sample() is None
    assert instance.state == ConnectorState.RUNNING  # an oversized reading is not a connectivity failure


def test_non_json_serializable_payload_is_discarded_not_a_crash():
    instance, fake = _configured_instance()
    instance.start()
    fake.next_sample = SensorSample(sensor_id='robot_front_rgb', timestamp_ms=1.0, sequence_id=1,
                                     data_type='custom', payload=object())
    assert instance.sample() is None
    assert instance.state == ConnectorState.RUNNING


# --- stop / repeated stop -----------------------------------------------------

def test_stop_transitions_to_stopped():
    instance, fake = _configured_instance()
    instance.start()
    instance.stop()
    assert instance.state == ConnectorState.STOPPED
    assert fake.stop_calls == 1


def test_repeated_stop_while_stopped_is_a_no_op():
    instance, fake = _configured_instance()
    instance.stop()
    instance.stop()
    assert fake.stop_calls == 0  # never RUNNING in the first place, nothing to stop
    instance.start()
    instance.stop()
    instance.stop()
    assert fake.stop_calls == 1


# --- runtime failure -----------------------------------------------------------

def test_stop_failure_raises_and_moves_to_failed():
    instance, fake = _configured_instance()
    instance.start()
    fake.fail_stop = True
    with pytest.raises(ConnectorRuntimeError):
        instance.stop()
    assert instance.state == ConnectorState.FAILED
    # A subsequent stop() is a no-op relative to FAILED, not STOPPED -
    # never silently claims success it didn't achieve.
    fake.fail_stop = False


# --- two sensor instances sharing one connector implementation ---------------

def test_two_sensor_instances_of_the_same_connector_class_stay_fully_independent():
    front = ConnectorInstance('ridesafe_front_rgb', 'multisens.builtin.sensor.rtsp', _FakeConnector())
    rear = ConnectorInstance('ridesafe_rear_rgb', 'multisens.builtin.sensor.rtsp', _FakeConnector())

    front.configure({'uri': 'rtsp://example/front'})
    rear.configure({'uri': 'rtsp://example/rear'})
    front.start()

    assert front.state == ConnectorState.RUNNING
    assert rear.state == ConnectorState.STOPPED  # starting front never starts rear
    assert front.sensor_id == 'ridesafe_front_rgb'
    assert rear.sensor_id == 'ridesafe_rear_rgb'

    rear.start()
    front.stop()
    assert front.state == ConnectorState.STOPPED
    assert rear.state == ConnectorState.RUNNING  # stopping front never stops rear
