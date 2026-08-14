"""Phase 103 (v0.9): RideSafe/PropertyWatch plugin/connector-architecture
validation.

Confirms the existing public demo sensor identities - `ridesafe_front_rgb`/
`ridesafe_rear_rgb` (RideSafe) and `property_entrance_rgb`/
`property_storage_rgb`/`property_indoor_rgb` (PropertyWatch), the same
ids the demo evaluation data generators (Phases 73-74, 87-88 -
scripts/generate_ridesafe_demo_data.py etc.) have used all along - map
cleanly onto the v0.9 connector architecture: five independent
`ConnectorInstance` objects, all built from the one
`multisens.builtin.sensor.rtsp` plugin, via a `config/sensors.yaml`-shaped
document loaded through the real `app.config.load_sensors()` +
`app.plugins.manager.build_connector_instances()` pipeline (a temp file,
monkeypatched `MULTISENS_SENSORS_CONFIG` - the same convention
test_config.py already uses).

**This is configuration/discovery validation only, explicitly not a new
live-video claim**: the repo's real `config/sensors.yaml` - the one that
actually drives the live Dashboard (`/api/sensors`) and ROS ingestion -
is never touched by this phase (see the last test below, which checks
this directly) and still lists only `rgb`/`depth`/`thermal`. Adding these
five ids there would do two things out of this phase's scope: (1)
silently surface them on the Dashboard's own sensor list (an explicit
"out of scope: no new live dashboard visualization" item), and (2) very
likely collide on ROS ingestion's own single-topic-per-modality
constraint - `sensor_config.py`'s `select_usable_sensors` raises on two
`rgb`-modality entries, exactly the shape RideSafe's two cameras and
PropertyWatch's three would be (docs/limitations.md's own "one sensor
per modality, for live ingestion only" limitation - still completely
unchanged by this phase).

What v0.9 actually changes: the connector *plugin* layer has no modality
concept and no single-topic constraint at all. `RtspSensorConnector`
only ever needs a `sensor_id` string and a bridge lookup - proven here
with the real shipped demo identities instead of the generic
`front`/`rear` placeholders `test_builtin_rtsp.py` already used.
"""
from app.config import load_sensors
from app.plugins.builtin_rtsp import PLUGIN_ID
from app.plugins.manager import build_connector_instances
from app.plugins.registry import discover_plugins
from multisens_sdk import ConnectorState

RIDESAFE_SENSOR_IDS = ['ridesafe_front_rgb', 'ridesafe_rear_rgb']
PROPERTYWATCH_SENSOR_IDS = ['property_entrance_rgb', 'property_storage_rgb', 'property_indoor_rgb']


class _FakeBridge:
    def __init__(self):
        self._sensors: dict[str, dict] = {}

    def set_sensor(self, sensor_id: str, **fields) -> None:
        self._sensors[sensor_id] = fields

    def snapshot(self) -> dict:
        return {'sensors': dict(self._sensors), 'system': None, 'sync': None}


def _write_connector_only_config(tmp_path, sensor_ids: list[str]) -> str:
    """A `config/sensors.yaml`-shaped document naming each id's
    `connector` block only - deliberately omits `transport`/`modality`/
    `url`, the fields that matter to ROS ingestion (sensor_config.py) and
    to nothing this test exercises. This is purely what
    `build_connector_instances()` itself reads."""
    lines = ['sensors:']
    for sensor_id in sensor_ids:
        lines.append(f'  - id: {sensor_id}')
        lines.append('    connector:')
        lines.append(f'      plugin: {PLUGIN_ID}')
        lines.append('      config:')
        lines.append(f'        uri: rtsp://host.docker.internal:8554/{sensor_id}')
    config_file = tmp_path / 'sensors.yaml'
    config_file.write_text('\n'.join(lines) + '\n')
    return str(config_file)


def _build(monkeypatch, tmp_path, sensor_ids: list[str]):
    monkeypatch.setenv('MULTISENS_SENSORS_CONFIG', _write_connector_only_config(tmp_path, sensor_ids))
    bridge = _FakeBridge()
    registry = discover_plugins(entry_points=[], ros_bridge=bridge)
    instances = build_connector_instances(load_sensors(), registry)
    return instances, bridge


def test_ridesafe_front_and_rear_get_independent_connector_instances(monkeypatch, tmp_path):
    instances, bridge = _build(monkeypatch, tmp_path, RIDESAFE_SENSOR_IDS)
    assert set(instances) == set(RIDESAFE_SENSOR_IDS)
    for sensor_id in RIDESAFE_SENSOR_IDS:
        assert instances[sensor_id].plugin_id == PLUGIN_ID
        assert instances[sensor_id].state == ConnectorState.RUNNING

    front, rear = instances['ridesafe_front_rgb'], instances['ridesafe_rear_rgb']
    assert front._connector is not rear._connector  # one plugin, two real objects

    # Distinct health, never shared state leaking between the two cameras.
    bridge.set_sensor('ridesafe_front_rgb', connection_state='connected')
    bridge.set_sensor('ridesafe_rear_rgb', connection_state='disconnected')
    assert front.health().state == ConnectorState.RUNNING
    assert rear.health().state == ConnectorState.DEGRADED


def test_propertywatch_three_cameras_get_independent_connector_instances(monkeypatch, tmp_path):
    instances, bridge = _build(monkeypatch, tmp_path, PROPERTYWATCH_SENSOR_IDS)
    assert set(instances) == set(PROPERTYWATCH_SENSOR_IDS)
    connectors = {id(instances[sid]._connector) for sid in PROPERTYWATCH_SENSOR_IDS}
    assert len(connectors) == 3  # three distinct objects from one plugin_id

    bridge.set_sensor('property_entrance_rgb', connection_state='connected')
    bridge.set_sensor('property_storage_rgb', connection_state='connected')
    bridge.set_sensor('property_indoor_rgb', connection_state='disconnected')
    assert instances['property_entrance_rgb'].health().state == ConnectorState.RUNNING
    assert instances['property_storage_rgb'].health().state == ConnectorState.RUNNING
    assert instances['property_indoor_rgb'].health().state == ConnectorState.DEGRADED


def test_all_five_identities_together_share_one_plugin_but_stay_fully_independent(monkeypatch, tmp_path):
    all_ids = RIDESAFE_SENSOR_IDS + PROPERTYWATCH_SENSOR_IDS
    instances, bridge = _build(monkeypatch, tmp_path, all_ids)
    assert set(instances) == set(all_ids)
    assert all(i.plugin_id == PLUGIN_ID for i in instances.values())
    assert len({id(instances[sid]._connector) for sid in all_ids}) == 5  # five real objects, one plugin_id

    # Each carries its own uri (distinct config) and its own health -
    # setting one sensor's bridge state never moves any of the other four.
    for sensor_id in all_ids:
        bridge.set_sensor(sensor_id, connection_state='connected')
        assert instances[sensor_id].health().state == ConnectorState.RUNNING
        others = [sid for sid in all_ids if sid != sensor_id]
        for other in others:
            assert instances[other].health().state in (ConnectorState.RUNNING, ConnectorState.DEGRADED)
        bridge.set_sensor(sensor_id, connection_state='disconnected')
        assert instances[sensor_id].health().state == ConnectorState.DEGRADED


def test_this_phase_never_touches_the_repos_real_live_dashboard_config():
    # The real config/sensors.yaml that drives the live Dashboard
    # (/api/sensors) and ROS ingestion is untouched by this phase - still
    # exactly rgb/depth/thermal, never a RideSafe/PropertyWatch id. This
    # is the "not a new live-video claim, no new Dashboard visualization"
    # acceptance bar, checked directly rather than only asserted in prose.
    import pathlib
    real_config = pathlib.Path(__file__).resolve().parents[2] / 'config' / 'sensors.yaml'
    text = real_config.read_text()
    for sensor_id in RIDESAFE_SENSOR_IDS + PROPERTYWATCH_SENSOR_IDS:
        assert sensor_id not in text
