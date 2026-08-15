import textwrap

from app.config import (
    load_disabled_plugin_ids,
    load_platform_id,
    load_poll_connectors,
    load_resource_collectors,
    load_sensors,
)
from app.domain.resources import UNKNOWN_PLATFORM_ID


def test_load_sensors_returns_empty_list_when_file_missing(monkeypatch, tmp_path):
    monkeypatch.setenv('MULTISENS_SENSORS_CONFIG', str(tmp_path / 'does-not-exist.yaml'))
    assert load_sensors() == []


def test_load_sensors_parses_real_config(monkeypatch, tmp_path):
    config_file = tmp_path / 'sensors.yaml'
    config_file.write_text(textwrap.dedent("""\
        sensors:
          - id: rgb
            modality: rgb
            source_type: physical
            transport: rtsp
            url: rtsp://example/rgb
            expected_fps: 30
    """))
    monkeypatch.setenv('MULTISENS_SENSORS_CONFIG', str(config_file))

    sensors = load_sensors()

    assert sensors == [{
        'id': 'rgb',
        'modality': 'rgb',
        'source_type': 'physical',
        'transport': 'rtsp',
        'url': 'rtsp://example/rgb',
        'expected_fps': 30,
    }]


def test_load_sensors_handles_empty_file(monkeypatch, tmp_path):
    config_file = tmp_path / 'sensors.yaml'
    config_file.write_text('')
    monkeypatch.setenv('MULTISENS_SENSORS_CONFIG', str(config_file))

    assert load_sensors() == []


def test_load_sensors_handles_a_bare_list_document_without_crashing(monkeypatch, tmp_path):
    # A malformed file (the 'sensors:' key accidentally omitted, just its
    # list body pasted directly) must degrade to "no sensors configured,"
    # never an unhandled AttributeError from calling .get() on a list.
    config_file = tmp_path / 'sensors.yaml'
    config_file.write_text('- id: rgb\n  modality: rgb\n')
    monkeypatch.setenv('MULTISENS_SENSORS_CONFIG', str(config_file))

    assert load_sensors() == []


# --- v0.9 (Phase 94): plugins.disabled -------------------------------------

def test_load_disabled_plugin_ids_returns_empty_list_when_file_missing(monkeypatch, tmp_path):
    monkeypatch.setenv('MULTISENS_SENSORS_CONFIG', str(tmp_path / 'does-not-exist.yaml'))
    assert load_disabled_plugin_ids() == []


def test_load_disabled_plugin_ids_returns_empty_list_when_absent(monkeypatch, tmp_path):
    config_file = tmp_path / 'sensors.yaml'
    config_file.write_text('sensors: []\n')
    monkeypatch.setenv('MULTISENS_SENSORS_CONFIG', str(config_file))
    assert load_disabled_plugin_ids() == []


def test_load_disabled_plugin_ids_parses_real_config(monkeypatch, tmp_path):
    config_file = tmp_path / 'sensors.yaml'
    config_file.write_text(textwrap.dedent("""\
        sensors: []
        plugins:
          disabled:
            - example.experimental-plugin
            - acme.sensor.broken
    """))
    monkeypatch.setenv('MULTISENS_SENSORS_CONFIG', str(config_file))
    assert load_disabled_plugin_ids() == ['example.experimental-plugin', 'acme.sensor.broken']


def test_load_disabled_plugin_ids_handles_malformed_shapes_without_crashing(monkeypatch, tmp_path):
    # 'plugins' present but not a mapping, and 'disabled' present but not
    # a list - both must degrade to "nothing disabled," never an
    # unhandled AttributeError/TypeError.
    config_file = tmp_path / 'sensors.yaml'
    config_file.write_text('sensors: []\nplugins: "not-a-mapping"\n')
    monkeypatch.setenv('MULTISENS_SENSORS_CONFIG', str(config_file))
    assert load_disabled_plugin_ids() == []

    config_file.write_text('sensors: []\nplugins:\n  disabled: "not-a-list"\n')
    assert load_disabled_plugin_ids() == []


# --- v0.9 bug hunt (issue #110): poll_connectors ----------------------------

def test_load_poll_connectors_returns_empty_list_when_file_missing(monkeypatch, tmp_path):
    monkeypatch.setenv('MULTISENS_SENSORS_CONFIG', str(tmp_path / 'does-not-exist.yaml'))
    assert load_poll_connectors() == []


def test_load_poll_connectors_returns_empty_list_when_absent(monkeypatch, tmp_path):
    config_file = tmp_path / 'sensors.yaml'
    config_file.write_text('sensors: []\n')
    monkeypatch.setenv('MULTISENS_SENSORS_CONFIG', str(config_file))
    assert load_poll_connectors() == []


def test_load_poll_connectors_parses_real_config(monkeypatch, tmp_path):
    config_file = tmp_path / 'sensors.yaml'
    config_file.write_text(textwrap.dedent("""\
        sensors: []
        poll_connectors:
          - id: acme-predictions
            plugin: acme.prediction.detector
            config:
              endpoint: https://example/predict
            poll_interval_s: 2.0
    """))
    monkeypatch.setenv('MULTISENS_SENSORS_CONFIG', str(config_file))

    assert load_poll_connectors() == [{
        'id': 'acme-predictions',
        'plugin': 'acme.prediction.detector',
        'config': {'endpoint': 'https://example/predict'},
        'poll_interval_s': 2.0,
    }]


def test_load_poll_connectors_handles_malformed_shape_without_crashing(monkeypatch, tmp_path):
    config_file = tmp_path / 'sensors.yaml'
    config_file.write_text('sensors: []\npoll_connectors: "not-a-list"\n')
    monkeypatch.setenv('MULTISENS_SENSORS_CONFIG', str(config_file))
    assert load_poll_connectors() == []


# --- v0.9.1 (issue #111): resource_collectors -------------------------------

def test_load_resource_collectors_returns_empty_list_when_file_missing(monkeypatch, tmp_path):
    monkeypatch.setenv('MULTISENS_SENSORS_CONFIG', str(tmp_path / 'does-not-exist.yaml'))
    assert load_resource_collectors() == []


def test_load_resource_collectors_returns_empty_list_when_absent(monkeypatch, tmp_path):
    config_file = tmp_path / 'sensors.yaml'
    config_file.write_text('sensors: []\n')
    monkeypatch.setenv('MULTISENS_SENSORS_CONFIG', str(config_file))
    assert load_resource_collectors() == []


def test_load_resource_collectors_parses_real_config(monkeypatch, tmp_path):
    config_file = tmp_path / 'sensors.yaml'
    config_file.write_text(textwrap.dedent("""\
        sensors: []
        resource_collectors:
          - id: battery-monitor
            plugin: acme.resource.battery
            config:
              device: /dev/battery0
            poll_interval_s: 5.0
    """))
    monkeypatch.setenv('MULTISENS_SENSORS_CONFIG', str(config_file))

    assert load_resource_collectors() == [{
        'id': 'battery-monitor',
        'plugin': 'acme.resource.battery',
        'config': {'device': '/dev/battery0'},
        'poll_interval_s': 5.0,
    }]


def test_load_resource_collectors_handles_malformed_shape_without_crashing(monkeypatch, tmp_path):
    config_file = tmp_path / 'sensors.yaml'
    config_file.write_text('sensors: []\nresource_collectors: "not-a-list"\n')
    monkeypatch.setenv('MULTISENS_SENSORS_CONFIG', str(config_file))
    assert load_resource_collectors() == []


# --- v0.9.1 (issue #111): platform_id ----------------------------------------

def test_load_platform_id_falls_back_to_unknown_when_file_missing(monkeypatch, tmp_path):
    monkeypatch.setenv('MULTISENS_SENSORS_CONFIG', str(tmp_path / 'does-not-exist.yaml'))
    assert load_platform_id() == UNKNOWN_PLATFORM_ID


def test_load_platform_id_falls_back_to_unknown_when_absent(monkeypatch, tmp_path):
    config_file = tmp_path / 'sensors.yaml'
    config_file.write_text('sensors: []\n')
    monkeypatch.setenv('MULTISENS_SENSORS_CONFIG', str(config_file))
    assert load_platform_id() == UNKNOWN_PLATFORM_ID


def test_load_platform_id_parses_a_declared_value(monkeypatch, tmp_path):
    config_file = tmp_path / 'sensors.yaml'
    config_file.write_text('sensors: []\nplatform_id: jetson-orin-01\n')
    monkeypatch.setenv('MULTISENS_SENSORS_CONFIG', str(config_file))
    assert load_platform_id() == 'jetson-orin-01'


def test_load_platform_id_falls_back_to_unknown_for_a_malformed_value(monkeypatch, tmp_path):
    config_file = tmp_path / 'sensors.yaml'
    config_file.write_text('sensors: []\nplatform_id: 123\n')
    monkeypatch.setenv('MULTISENS_SENSORS_CONFIG', str(config_file))
    assert load_platform_id() == UNKNOWN_PLATFORM_ID
