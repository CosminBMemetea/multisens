"""REST endpoint tests. Deliberately does NOT use TestClient as a context
manager (`with TestClient(app) as client:`), which is what triggers
FastAPI's lifespan startup/shutdown - these tests exercise routing and
response behavior, not the live ROS bridge, so bridge.start() (a real
rclpy.init() + background thread) never needs to run for them.
"""
import textwrap

import pytest
from fastapi.testclient import TestClient

from app.domain.resources import SUPPORTED_RESOURCE_METRICS, register_resource_metrics
from app.main import app
from multisens_sdk import ResourceMetricDescriptor


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


# --- v0.9 bug hunt (issue #116): GET /api/resource-metrics --------------------

@pytest.fixture
def clean_supported_resource_metrics():
    """SUPPORTED_RESOURCE_METRICS is genuine shared module-level state -
    same save/restore discipline test_external_resource_collector_plugin.py
    already established for it."""
    original = dict(SUPPORTED_RESOURCE_METRICS)
    yield SUPPORTED_RESOURCE_METRICS
    SUPPORTED_RESOURCE_METRICS.clear()
    SUPPORTED_RESOURCE_METRICS.update(original)


def test_resource_metrics_returns_the_built_in_vocabulary_sorted(clean_supported_resource_metrics):
    client = TestClient(app)
    response = client.get('/api/resource-metrics')
    assert response.status_code == 200
    body = response.json()
    assert body == sorted(body)
    assert set(body) == {
        'cpu_percent', 'memory_mb', 'network_receive_mbps', 'network_transmit_mbps', 'fps', 'pipeline_latency_ms',
    }


def test_resource_metrics_reflects_a_plugin_registered_metric(clean_supported_resource_metrics):
    # The whole point of issue #116: this endpoint must reflect runtime
    # registration (app/domain/resources.py's own register_resource_metrics,
    # v0.9 Phase 99), not a frozen-at-import-time list - a
    # RESOURCE_COLLECTOR plugin's metric becomes visible here the moment
    # it's discovered, without a frontend rebuild.
    register_resource_metrics([ResourceMetricDescriptor(metric='battery_percent', unit='%')])
    client = TestClient(app)
    response = client.get('/api/resource-metrics')
    assert response.status_code == 200
    assert 'battery_percent' in response.json()
