"""Plugin identity, versioning, and the shared connector health/lifecycle
shapes - new in v0.9, Phase 93. See docs/plugin-sdk.md in the main
repository for the full decision record these types implement.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

# Bumped only on a breaking multisens_sdk contract change - deliberately
# decoupled from the MultiSens application's own 0.9/0.10/1.0 release
# numbering. Exact-match compatibility only in v0.9: a plugin declaring a
# different api_version is INCOMPATIBLE, never guessed as forward/backward
# compatible - see docs/plugin-sdk.md#versioning-three-independent-axes.
MULTISENS_PLUGIN_API_VERSION = "1"


class PluginType(str, Enum):
    SENSOR_CONNECTOR = "sensor_connector"
    PREDICTION_CONNECTOR = "prediction_connector"
    GROUND_TRUTH_CONNECTOR = "ground_truth_connector"
    EVALUATOR = "evaluator"
    RESOURCE_COLLECTOR = "resource_collector"


@dataclass(frozen=True)
class PluginDescriptor:
    """Every executable plugin's own `descriptor()` method returns one of
    these - the single authoritative source of plugin metadata (never a
    separate, potentially-divergent manifest file). `plugin_id` is
    `namespace.category.name` (e.g. `multisens.builtin.sensor.rtsp`,
    `acme.sensor.velodyne-lidar`) - lowercase, one global id namespace
    across every PluginType, never the display name."""
    plugin_id: str
    name: str
    version: str
    plugin_type: PluginType
    api_version: str
    capabilities: dict[str, Any] = field(default_factory=dict)
    author: str = ""
    license: str = ""
    description: str = ""
    homepage: str | None = None


class ConnectorState(str, Enum):
    """Per-instance runtime state, observed via `health()` - tracked
    separately from plugin installation status (AVAILABLE/INCOMPATIBLE/
    LOAD_FAILED/DISABLED, a registry-level concern, not a connector one).
    Deliberately flattened from a literal DISCOVERED/CONFIGURED/STARTING/
    RUNNING/STOPPING/STOPPED diagram - DISCOVERED/CONFIGURED are
    registry-tracked booleans, not states a connector itself reports, and
    STOPPING is dropped by making `stop()` synchronous (blocks until
    actually STOPPED or raises) rather than leaving a limbo state to
    poll."""
    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    DEGRADED = "degraded"
    FAILED = "failed"


@dataclass(frozen=True)
class ConnectorHealth:
    """Generic across every connector-shaped plugin type - never a
    plugin-specific health field in this shared shape; anything
    plugin-specific belongs in `details`."""
    state: ConnectorState
    last_sample_age_s: float | None = None   # None = no sample yet
    message: str | None = None
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SensorSample:
    """Small, control-plane-sized sensor data only - scalar/vector/pose/
    IMU-ish payloads. Never raw image bytes or point-cloud arrays; those
    flow through ROS/native transport directly, never through this
    object - see docs/plugin-sdk.md#data-plane-vs-control-plane."""
    sensor_id: str
    timestamp_ms: float
    sequence_id: int | None
    data_type: str            # open string ("scalar"/"vector"/"pose"/"imu"/...) - never exhaustively enumerated here
    payload: Any                # small, JSON-serializable control-plane data only
    metadata: dict[str, Any] = field(default_factory=dict)


class PluginError(Exception):
    """Base class for every SDK-defined plugin error."""


class ConnectorConfigError(PluginError):
    """Raised by a connector's own `configure()` for invalid/missing
    configuration - caught at the call site, never left to surface as an
    unhandled exception or a mysterious later failure."""
