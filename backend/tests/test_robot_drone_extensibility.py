"""Phase 104 (v0.9): Robot/Drone Extensibility Validation.

Builds the architecture review's own `robot_lidar`/`robot_imu` paper
design (docs/plugin-sdk.md, Phase 92 - the hypothetical connectors that
review's own zero-core-imports test walked through on paper) as small,
real, test-only plugins -
`tests/fixtures/robot_drone_plugin/{lidar,imu}.py` - reusing Phase 101's
reference-plugin pattern (deterministic synthetic data, the identical
AST-based SDK-boundary check) but deliberately never shipped as a public
`examples/` package: these exist purely inside this test suite to prove
the SDK against a robotics-flavored scenario, matching this project's
own RideSafe/PropertyWatch/Robot-Drone-Lab public-demo vocabulary.

**What this proves**: a connector for LiDAR/IMU-shaped data can be
discovered, configured, started, sampled, and health-reported - and
really registered through `discover_plugins()`, not just asserted in
isolation - using nothing but `multisens_sdk` + the standard library.
Zero `backend.app`/`frontend`/`ros2_ws` imports anywhere in either
fixture file, checked by the exact same AST walk
`examples/plugins/environment-sensor/tests/test_boundary.py` already
established for Phase 101's shipped reference plugin.

**What this does NOT prove, and never claims**: that MultiSens
understands LiDAR point-cloud geometry or IMU signal semantics.
`sample()` on both fixtures emits a tiny, generic, JSON-serializable
summary (`point_count`/`range_m`; six raw accel/gyro axes) - never raw
point-cloud data, never orientation estimation or sensor fusion - and no
point-cloud/IMU-specific processing exists anywhere in these fixtures or
in MultiSens core. "Can register/route a connector" is never conflated
with "core understands the domain."
"""
import ast
from pathlib import Path
from types import SimpleNamespace

import pytest
from app.plugins.registry import PluginStatus, discover_plugins
from multisens_sdk import ConnectorConfigError, PluginType
from multisens_sdk.testing import (
    assert_connector_lifecycle,
    assert_health_contract,
    assert_valid_plugin_descriptor,
)
from tests.fixtures.robot_drone_plugin.imu import PLUGIN_ID as IMU_PLUGIN_ID
from tests.fixtures.robot_drone_plugin.imu import RobotImuConnector
from tests.fixtures.robot_drone_plugin.lidar import PLUGIN_ID as LIDAR_PLUGIN_ID
from tests.fixtures.robot_drone_plugin.lidar import RobotLidarConnector

FIXTURE_DIR = Path(__file__).parent / 'fixtures' / 'robot_drone_plugin'
FORBIDDEN_TOP_LEVEL_IMPORTS = ('app', 'backend', 'frontend', 'ros2_ws')
ALLOWED_IMPORTS = {'typing', '__future__', 'multisens_sdk'}


def _imported_top_level_names(py_file: Path) -> set[str]:
    tree = ast.parse(py_file.read_text(), filename=str(py_file))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name.split('.')[0])
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                names.add(node.module.split('.')[0])
    return names


# --- the actual clean-room test (mirrors Phase 101's test_boundary.py) ------

def test_fixture_plugins_import_nothing_from_multisens_internals():
    py_files = sorted(FIXTURE_DIR.glob('*.py'))
    assert py_files, f'no .py files found under {FIXTURE_DIR} - the search path itself is broken'
    for py_file in py_files:
        forbidden = _imported_top_level_names(py_file) & set(FORBIDDEN_TOP_LEVEL_IMPORTS)
        assert not forbidden, f'{py_file} imports forbidden module(s): {forbidden}'


def test_fixture_plugins_only_depend_on_multisens_sdk_and_stdlib():
    for py_file in sorted(FIXTURE_DIR.glob('*.py')):
        imported = _imported_top_level_names(py_file)
        unexpected = imported - ALLOWED_IMPORTS
        assert not unexpected, f'{py_file} imports unexpected module(s) beyond multisens_sdk/stdlib: {unexpected}'


# --- descriptor/lifecycle/health, using only multisens_sdk.testing ---------

def test_lidar_descriptor_is_valid_and_never_claims_point_cloud_understanding():
    descriptor = RobotLidarConnector().descriptor()
    assert_valid_plugin_descriptor(descriptor)
    assert descriptor.plugin_type == PluginType.SENSOR_CONNECTOR
    assert descriptor.capabilities['data_type'] == 'point_cloud_summary'  # a summary, never raw geometry


def test_imu_descriptor_is_valid():
    descriptor = RobotImuConnector().descriptor()
    assert_valid_plugin_descriptor(descriptor)
    assert descriptor.plugin_type == PluginType.SENSOR_CONNECTOR


def test_lidar_full_lifecycle_via_contract_helper():
    connector = RobotLidarConnector()
    assert_connector_lifecycle(connector, configure=lambda: connector.configure('robot_lidar', {}))


def test_imu_full_lifecycle_via_contract_helper():
    connector = RobotImuConnector()
    assert_connector_lifecycle(connector, configure=lambda: connector.configure('robot_imu', {}))


def test_lidar_rejects_invalid_scan_rate():
    connector = RobotLidarConnector()
    with pytest.raises(ConnectorConfigError, match='scan_rate_hz'):
        connector.configure('robot_lidar', {'scan_rate_hz': -1})


def test_lidar_sample_is_a_small_generic_summary_not_point_cloud_data():
    connector = RobotLidarConnector()
    connector.configure('robot_lidar', {})
    connector.start()
    sample = connector.sample()
    assert sample is not None
    assert sample.sensor_id == 'robot_lidar'
    assert sample.data_type == 'point_cloud_summary'
    assert set(sample.payload) == {'point_count', 'range_m'}
    assert isinstance(sample.payload['point_count'], int)
    assert sample.metadata['label'] == 'SYNTHETIC SAMPLE SOURCE'


def test_imu_sample_is_six_axis_and_synthetic():
    connector = RobotImuConnector()
    connector.configure('robot_imu', {})
    connector.start()
    sample = connector.sample()
    assert sample is not None
    assert sample.data_type == 'imu'
    assert set(sample.payload) == {'ax', 'ay', 'az', 'gx', 'gy', 'gz'}
    assert sample.metadata['label'] == 'SYNTHETIC SAMPLE SOURCE'


def test_samples_are_deterministic_across_a_fresh_run():
    a = RobotLidarConnector()
    a.configure('robot_lidar', {})
    a.start()
    b = RobotLidarConnector()
    b.configure('robot_lidar', {})
    b.start()
    assert [a.sample().payload for _ in range(5)] == [b.sample().payload for _ in range(5)]


def test_health_contract_for_both():
    for connector in (RobotLidarConnector(), RobotImuConnector()):
        assert_health_contract(connector.health())


# --- real registration through discover_plugins() ---------------------------

def test_both_fixtures_register_as_available_through_real_discovery():
    entry_points = [
        SimpleNamespace(name=LIDAR_PLUGIN_ID, load=lambda: RobotLidarConnector,
                         dist=SimpleNamespace(name='robot-drone-test-fixture', version='0.1.0')),
        SimpleNamespace(name=IMU_PLUGIN_ID, load=lambda: RobotImuConnector,
                         dist=SimpleNamespace(name='robot-drone-test-fixture', version='0.1.0')),
    ]
    registry = discover_plugins(entry_points=entry_points)
    for plugin_id in (LIDAR_PLUGIN_ID, IMU_PLUGIN_ID):
        record = registry.get(plugin_id)
        assert record is not None
        assert record.status == PluginStatus.AVAILABLE
        assert record.factory is not None
        assert record.factory() is not record.factory()  # a fresh connector object every call
