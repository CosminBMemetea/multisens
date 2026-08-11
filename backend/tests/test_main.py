"""REST endpoint tests. Deliberately does NOT use TestClient as a context
manager (`with TestClient(app) as client:`), which is what triggers
FastAPI's lifespan startup/shutdown - these tests exercise routing and
response behavior, not the live ROS bridge, so bridge.start() (a real
rclpy.init() + background thread) never needs to run for them.
"""
import textwrap

from fastapi.testclient import TestClient

from app.main import app


def test_health_returns_ok():
    client = TestClient(app)
    response = client.get('/api/health')
    assert response.status_code == 200
    assert response.json() == {'status': 'ok'}


def test_sensors_returns_configured_list(monkeypatch, tmp_path):
    config_file = tmp_path / 'sensors.yaml'
    config_file.write_text(textwrap.dedent("""\
        sensors:
          - id: rgb
            modality: rgb
            source_type: physical
            transport: rtsp
            url: rtsp://example/rgb
    """))
    monkeypatch.setenv('MULTISENS_SENSORS_CONFIG', str(config_file))

    client = TestClient(app)
    response = client.get('/api/sensors')

    assert response.status_code == 200
    assert response.json()[0]['id'] == 'rgb'


def test_sensors_empty_when_no_config(monkeypatch, tmp_path):
    monkeypatch.setenv('MULTISENS_SENSORS_CONFIG', str(tmp_path / 'missing.yaml'))
    client = TestClient(app)
    assert client.get('/api/sensors').json() == []


def test_stream_returns_404_for_unknown_sensor(monkeypatch, tmp_path):
    config_file = tmp_path / 'sensors.yaml'
    config_file.write_text('sensors: []\n')
    monkeypatch.setenv('MULTISENS_SENSORS_CONFIG', str(config_file))

    client = TestClient(app)
    response = client.get('/api/sensors/nonexistent/stream.mjpeg')

    assert response.status_code == 404
    assert 'nonexistent' in response.json()['error']


def test_status_returns_empty_snapshot_before_any_ros_data():
    client = TestClient(app)
    response = client.get('/api/status')
    assert response.status_code == 200
    assert response.json() == {'sensors': {}, 'system': None, 'sync': None}
