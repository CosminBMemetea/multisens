"""Phase 66: resource collection. `SystemMetricsWindow` is exercised for
real against psutil (no mocking) - the acceptance criterion is that this
collector produces genuinely measured rows against a real running
stack, and that its own overhead is measured, not asserted.
"""
import time
from datetime import datetime, timezone

import pytest

from app.resource_collector import SystemMetricsWindow, collect_sensor_metrics

PLATFORM_ID = 'test-platform'


# --- SystemMetricsWindow: real psutil, no mocks -----------------------------

def test_system_metrics_window_produces_real_measured_rows():
    window = SystemMetricsWindow()
    window.start()
    time.sleep(0.05)  # a real, if short, window - not zero-duration
    observations = window.end(session_id='s1', configuration_id='cfg-a', platform_id=PLATFORM_ID)

    by_metric = {o.metric: o for o in observations}
    assert set(by_metric) == {'cpu_percent', 'memory_mb', 'network_receive_mbps', 'network_transmit_mbps'}

    cpu = by_metric['cpu_percent']
    assert cpu.quality == 'measured'
    assert 0.0 <= cpu.value <= 100.0 * 64  # psutil can exceed 100% on multi-core hosts under load
    assert cpu.unit == '%'
    assert cpu.source == 'psutil.cpu_percent'
    assert cpu.platform_id == PLATFORM_ID
    assert cpu.session_id == 's1'
    assert cpu.configuration_id == 'cfg-a'
    assert cpu.started_at < cpu.ended_at

    memory = by_metric['memory_mb']
    assert memory.quality == 'measured'
    assert memory.value > 0  # a real host always has some memory in use
    assert memory.unit == 'MB'

    for metric in ('network_receive_mbps', 'network_transmit_mbps'):
        net = by_metric[metric]
        assert net.quality == 'measured'
        assert net.value >= 0.0  # a real delta over a real window is never negative
        assert net.unit == 'Mbps'


def test_system_metrics_window_end_before_start_raises():
    window = SystemMetricsWindow()
    with pytest.raises(RuntimeError, match='start'):
        window.end(session_id='s1', configuration_id=None, platform_id=PLATFORM_ID)


def test_system_metrics_window_unattributed_configuration_id_is_none():
    window = SystemMetricsWindow()
    window.start()
    observations = window.end(session_id='s1', configuration_id=None, platform_id=PLATFORM_ID)
    assert all(o.configuration_id is None for o in observations)


def test_system_metrics_window_reusable_across_multiple_windows():
    # Same collector instance, two independent windows - each end()
    # resets internal state so a second start()/end() pair works.
    window = SystemMetricsWindow()
    window.start()
    first = window.end(session_id='s1', configuration_id=None, platform_id=PLATFORM_ID)
    window.start()
    second = window.end(session_id='s1', configuration_id=None, platform_id=PLATFORM_ID)
    assert {o.id for o in first}.isdisjoint({o.id for o in second})


# --- overhead measurement (Phase 66's own explicit acceptance criterion) ---

def test_collector_overhead_is_negligible_against_a_real_collection_window():
    window = SystemMetricsWindow()
    iterations = 200
    started = time.perf_counter()
    for _ in range(iterations):
        window.start()
        window.end(session_id='s1', configuration_id=None, platform_id=PLATFORM_ID)
    elapsed_ms = (time.perf_counter() - started) * 1000
    per_pair_ms = elapsed_ms / iterations
    # Generous bound (module docstring documents ~0.02-0.05ms measured on
    # the reference container) - this asserts "negligible next to a
    # realistic 5-10s window," not a tight performance regression gate.
    assert per_pair_ms < 5.0, f'collector overhead {per_pair_ms:.3f}ms/pair exceeds the 5ms bound'


# --- collect_sensor_metrics: reuse, never a new measurement -----------------

def _snapshot(**sensors) -> dict:
    return {'sensors': sensors, 'system': None, 'sync': None}


def test_collect_sensor_metrics_translates_fps_and_latency_directly():
    snapshot = _snapshot(front_rgb={'fps_received': '29.8', 'publish_latency_ms': '3.14', 'level': 'ok'})
    started, ended = datetime.now(timezone.utc), datetime.now(timezone.utc)
    observations = collect_sensor_metrics(
        snapshot, ['front_rgb'], session_id='s1', configuration_id='cfg-front_rgb',
        platform_id=PLATFORM_ID, started_at=started, ended_at=ended,
    )
    by_metric = {o.metric: o for o in observations}
    assert by_metric['fps'].value == pytest.approx(29.8)
    assert by_metric['fps'].quality == 'measured'
    assert by_metric['fps'].source == 'ros_diagnostics:front_rgb:fps_received'
    assert by_metric['pipeline_latency_ms'].value == pytest.approx(3.14)
    assert by_metric['pipeline_latency_ms'].quality == 'measured'


def test_collect_sensor_metrics_zero_fps_is_measured_not_unavailable():
    # fps_received == 0.0 while disconnected is a genuine measurement
    # ("no frames received recently"), never treated as missing evidence.
    snapshot = _snapshot(front_rgb={'fps_received': '0.0', 'publish_latency_ms': 'unavailable', 'level': 'error'})
    now = datetime.now(timezone.utc)
    observations = collect_sensor_metrics(
        snapshot, ['front_rgb'], session_id='s1', configuration_id=None,
        platform_id=PLATFORM_ID, started_at=now, ended_at=now,
    )
    by_metric = {o.metric: o for o in observations}
    assert by_metric['fps'].value == 0.0
    assert by_metric['fps'].quality == 'measured'


def test_collect_sensor_metrics_unavailable_latency_string_becomes_unavailable_row():
    snapshot = _snapshot(front_rgb={'fps_received': '0.0', 'publish_latency_ms': 'unavailable', 'level': 'error'})
    now = datetime.now(timezone.utc)
    observations = collect_sensor_metrics(
        snapshot, ['front_rgb'], session_id='s1', configuration_id=None,
        platform_id=PLATFORM_ID, started_at=now, ended_at=now,
    )
    by_metric = {o.metric: o for o in observations}
    assert by_metric['pipeline_latency_ms'].value is None
    assert by_metric['pipeline_latency_ms'].quality == 'unavailable'


def test_collect_sensor_metrics_sensor_absent_from_snapshot_is_unavailable_not_zero():
    snapshot = _snapshot()  # empty - sensor never reported or has gone stale
    now = datetime.now(timezone.utc)
    observations = collect_sensor_metrics(
        snapshot, ['rear_rgb'], session_id='s1', configuration_id=None,
        platform_id=PLATFORM_ID, started_at=now, ended_at=now,
    )
    by_metric = {o.metric: o for o in observations}
    assert by_metric['fps'].value is None
    assert by_metric['fps'].quality == 'unavailable'
    assert by_metric['pipeline_latency_ms'].value is None
    assert by_metric['pipeline_latency_ms'].quality == 'unavailable'


def test_collect_sensor_metrics_multiple_sensors_independent():
    snapshot = _snapshot(
        front_rgb={'fps_received': '30.0', 'publish_latency_ms': '2.0'},
        rear_rgb={'fps_received': '29.5', 'publish_latency_ms': '2.5'},
    )
    now = datetime.now(timezone.utc)
    observations = collect_sensor_metrics(
        snapshot, ['front_rgb', 'rear_rgb'], session_id='s1', configuration_id='cfg-front_rgb-rear_rgb',
        platform_id=PLATFORM_ID, started_at=now, ended_at=now,
    )
    fps_by_source = {o.source: o.value for o in observations if o.metric == 'fps'}
    assert fps_by_source == {
        'ros_diagnostics:front_rgb:fps_received': 30.0,
        'ros_diagnostics:rear_rgb:fps_received': 29.5,
    }
