import textwrap

from app.config import load_sensors


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
