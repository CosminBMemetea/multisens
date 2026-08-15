"""No launch_ros/rclpy import anywhere in this file or in sensor_config -
run with plain pytest, no live ROS environment needed."""
import textwrap

import pytest
from multisens_ingestion.sensor_config import load_sensors_config, select_usable_sensors


def test_load_sensors_config_parses_real_file(tmp_path):
    config_file = tmp_path / 'sensors.yaml'
    config_file.write_text(textwrap.dedent("""\
        sensors:
          - id: rgb
            modality: rgb
            source_type: physical
            transport: rtsp
            url: rtsp://example/rgb
    """))

    sensors = load_sensors_config(str(config_file))

    assert len(sensors) == 1
    assert sensors[0]['id'] == 'rgb'


def test_load_sensors_config_missing_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_sensors_config(str(tmp_path / 'nonexistent.yaml'))


def test_select_usable_sensors_passes_through_valid_entries():
    sensors = [
        {'id': 'rgb', 'modality': 'rgb', 'transport': 'rtsp'},
        {'id': 'depth', 'modality': 'depth', 'transport': 'rtsp'},
    ]
    assert select_usable_sensors(sensors) == sensors


def test_select_usable_sensors_rejects_duplicate_id():
    sensors = [
        {'id': 'front_rgb', 'modality': 'rgb', 'transport': 'rtsp'},
        {'id': 'front_rgb', 'modality': 'rgb', 'transport': 'rtsp'},
    ]
    with pytest.raises(ValueError, match='duplicate sensor id'):
        select_usable_sensors(sensors, config_path='test.yaml')


def test_select_usable_sensors_allows_two_sensors_sharing_one_modality():
    # v1.0-RC, issue #121: two RGB cameras (different ids) must be legal -
    # topics are keyed by id now, so there is no collision to guard against.
    sensors = [
        {'id': 'ridesafe_front_rgb', 'modality': 'rgb', 'transport': 'rtsp'},
        {'id': 'ridesafe_rear_rgb', 'modality': 'rgb', 'transport': 'rtsp'},
    ]
    assert select_usable_sensors(sensors) == sensors


def test_select_usable_sensors_skips_unsupported_transport():
    sensors = [
        {'id': 'rgb', 'modality': 'rgb', 'transport': 'rtsp'},
        {'id': 'weird', 'modality': 'weird', 'transport': 'gstreamer'},
    ]
    result = select_usable_sensors(sensors)
    assert [s['id'] for s in result] == ['rgb']


def test_select_usable_sensors_defaults_missing_transport_to_rtsp():
    sensors = [{'id': 'rgb', 'modality': 'rgb'}]
    assert select_usable_sensors(sensors) == sensors


def test_select_usable_sensors_empty_input_returns_empty():
    assert select_usable_sensors([]) == []
