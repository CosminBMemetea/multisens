"""No rclpy/message_filters/diagnostic_msgs import anywhere in this file or
in sync_logic - run with plain pytest, no live ROS environment needed."""
from multisens_sync.sync_logic import compute_sync_status


def test_all_synchronized_within_tolerance_is_ok():
    result = compute_sync_status(
        sensor_ids=['rgb', 'depth'], missing=[], stale=[], group_is_fresh=True,
        max_skew_ms=2.0, offsets_ms={'rgb': 1.0, 'depth': -1.0},
        tolerance_ms=25.0, group_rate_hz=30.0, stale_after_sec=3.0,
    )
    assert result['level'] == 'ok'
    assert result['fields']['max_skew_ms'] == '2.0'
    assert result['fields']['offset_ms_rgb'] == '1.0'
    assert result['fields']['offset_ms_depth'] == '-1.0'


def test_skew_over_tolerance_is_warn_not_error():
    result = compute_sync_status(
        sensor_ids=['rgb', 'depth'], missing=[], stale=[], group_is_fresh=True,
        max_skew_ms=40.0, offsets_ms={'rgb': 20.0, 'depth': -20.0},
        tolerance_ms=25.0, group_rate_hz=30.0, stale_after_sec=3.0,
    )
    assert result['level'] == 'warn'


def test_no_fresh_group_is_error_with_unavailable_fields():
    # Regression test: this must report "unavailable", never stale numbers
    # dressed up as current.
    result = compute_sync_status(
        sensor_ids=['rgb', 'depth'], missing=[], stale=['rgb', 'depth'], group_is_fresh=False,
        max_skew_ms=None, offsets_ms={},
        tolerance_ms=25.0, group_rate_hz=0.0, stale_after_sec=3.0,
    )
    assert result['level'] == 'error'
    assert result['fields']['max_skew_ms'] == 'unavailable'
    assert result['fields']['offset_ms_rgb'] == 'unavailable'
    assert result['fields']['offset_ms_depth'] == 'unavailable'


def test_missing_sensor_is_error():
    result = compute_sync_status(
        sensor_ids=['rgb', 'depth', 'thermal'], missing=['thermal'], stale=[], group_is_fresh=True,
        max_skew_ms=1.0, offsets_ms={'rgb': 0.5, 'depth': -0.5},
        tolerance_ms=25.0, group_rate_hz=30.0, stale_after_sec=3.0,
    )
    assert result['level'] == 'error'
    assert 'thermal' in result['message']
    assert result['fields']['missing_sensors'] == 'thermal'


def test_stale_but_group_fresh_is_warn():
    result = compute_sync_status(
        sensor_ids=['rgb', 'depth'], missing=[], stale=['depth'], group_is_fresh=True,
        max_skew_ms=1.0, offsets_ms={'rgb': 0.5, 'depth': -0.5},
        tolerance_ms=25.0, group_rate_hz=30.0, stale_after_sec=3.0,
    )
    assert result['level'] == 'warn'
    assert result['fields']['stale_sensors'] == 'depth'


def test_no_missing_or_stale_reports_none():
    result = compute_sync_status(
        sensor_ids=['rgb'], missing=[], stale=[], group_is_fresh=True,
        max_skew_ms=0.0, offsets_ms={'rgb': 0.0},
        tolerance_ms=25.0, group_rate_hz=30.0, stale_after_sec=3.0,
    )
    assert result['fields']['missing_sensors'] == 'none'
    assert result['fields']['stale_sensors'] == 'none'


def test_two_sensors_sharing_one_modality_get_independent_offset_fields():
    # v1.0-RC, issue #121: this function was already opaque-key-generic
    # (never actually depended on "modality" as a concept) - this pins
    # that down with participant ids that are NOT valid modality names,
    # proving no hidden assumption survived the rename.
    result = compute_sync_status(
        sensor_ids=['ridesafe_front_rgb', 'ridesafe_rear_rgb'], missing=[], stale=[], group_is_fresh=True,
        max_skew_ms=3.0, offsets_ms={'ridesafe_front_rgb': 1.5, 'ridesafe_rear_rgb': -1.5},
        tolerance_ms=25.0, group_rate_hz=30.0, stale_after_sec=3.0,
    )
    assert result['level'] == 'ok'
    assert result['fields']['offset_ms_ridesafe_front_rgb'] == '1.5'
    assert result['fields']['offset_ms_ridesafe_rear_rgb'] == '-1.5'
