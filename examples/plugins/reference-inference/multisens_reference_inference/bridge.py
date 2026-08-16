"""A thin `PredictionConnector` bridge (v1.0-RC, issue #123) - polls a
separately-running inference worker process's small local HTTP endpoint
(see the sibling `worker/` directory) and translates its latest
detection into canonical `Prediction` objects. Owns zero ML dependency
itself: imports only `multisens_sdk`, `urllib.request`, and the
standard library - the actual YOLOv8n model and its RTSP reader live in
a genuinely separate OS process, so a native-level crash there can
never take down this plugin or the MultiSens backend process it's
loaded into (v1.0-RC architecture review, process isolation).

A worker-down HTTP error surfaces as a plain exception from `poll()` -
deliberately not caught here. `PredictionConnectorInstance._poll_raw()`
(backend/app/plugins/poll_connector_instance.py) already isolates any
`poll()` exception into an empty list plus a recorded health message;
duplicating that handling here would just be a second copy of the same
guard.
"""
from __future__ import annotations

import json
import time
import urllib.request
from typing import Any

from multisens_sdk import (
    MULTISENS_PLUGIN_API_VERSION,
    ConnectorConfigError,
    ConnectorHealth,
    ConnectorState,
    PluginDescriptor,
    PluginType,
    Prediction,
)

PLUGIN_ID = 'multisens.reference.inference.yolo_bridge'
HOMEPAGE = 'https://github.com/CosminBMemetea/multisens/tree/main/examples/plugins/reference-inference'

# What the sibling worker/ process is built for - `configure()` rejects
# any other declared `modality` unless `allow_simulated_input: true` is
# explicitly set (issue #123, point 3).
SUPPORTED_MODALITIES = ('rgb',)
DEFAULT_TASK = 'vehicle_detection'
DEFAULT_TIMEOUT_S = 2.0


class YoloBridgeConnector:
    def __init__(self) -> None:
        self._session_id: str | None = None
        self._sensor_id: str | None = None
        self._worker_url: str | None = None
        self._task = DEFAULT_TASK
        self._timeout_s = DEFAULT_TIMEOUT_S
        self._active = False
        self._last_seen_frame_timestamp_ms: float | None = None
        self._last_poll_monotonic: float | None = None
        self._last_error: str | None = None

    def descriptor(self) -> PluginDescriptor:
        return PluginDescriptor(
            plugin_id=PLUGIN_ID, name='YOLOv8n Vehicle Detection Bridge', version='0.1.0',
            plugin_type=PluginType.PREDICTION_CONNECTOR, api_version=MULTISENS_PLUGIN_API_VERSION,
            capabilities={
                'supported_modalities': list(SUPPORTED_MODALITIES),
                'model': 'yolov8n',
                'classes': ['car', 'truck', 'bus', 'motorcycle'],
                'confidence_threshold': 0.40,
            },
            author='MultiSens Project', license='Apache-2.0', homepage=HOMEPAGE,
            description=(
                'Thin bridge to a separately-running YOLOv8n inference worker (see the sibling '
                'worker/ directory) - zero ML dependency itself, process-isolated from the '
                'actual model (v1.0-RC issue #123).'
            ),
        )

    def configure(self, config: dict[str, Any]) -> None:
        session_id = config.get('session_id')
        if not session_id or not isinstance(session_id, str):
            raise ConnectorConfigError("'session_id' is required and must be a non-empty string")
        sensor_id = config.get('sensor_id')
        if not sensor_id or not isinstance(sensor_id, str):
            raise ConnectorConfigError("'sensor_id' is required and must be a non-empty string")
        worker_url = config.get('worker_url')
        if not worker_url or not isinstance(worker_url, str):
            raise ConnectorConfigError("'worker_url' is required and must be a non-empty string")
        modality = config.get('modality')
        if not modality or not isinstance(modality, str):
            raise ConnectorConfigError(
                "'modality' is required and must be a non-empty string - the target sensor's own "
                "declared modality (config/sensors.yaml), checked against this plugin's "
                "supported_modalities since a plugin has no other way to know what it was pointed at"
            )
        allow_simulated_input = config.get('allow_simulated_input', False)
        if modality not in SUPPORTED_MODALITIES and not allow_simulated_input:
            raise ConnectorConfigError(
                f"modality '{modality}' is not in this plugin's supported_modalities "
                f"{SUPPORTED_MODALITIES} - set allow_simulated_input: true to override"
            )
        task = config.get('task', DEFAULT_TASK)
        if not isinstance(task, str) or not task:
            raise ConnectorConfigError("'task' must be a non-empty string if given")
        timeout_s = config.get('timeout_s', DEFAULT_TIMEOUT_S)
        if not isinstance(timeout_s, (int, float)) or isinstance(timeout_s, bool) or timeout_s <= 0:
            raise ConnectorConfigError(f"'timeout_s' must be a positive number, got {timeout_s!r}")

        self._session_id = session_id
        self._sensor_id = sensor_id
        self._worker_url = worker_url.rstrip('/')
        self._task = task
        self._timeout_s = float(timeout_s)
        self._last_seen_frame_timestamp_ms = None
        self._last_error = None

    def start(self) -> None:
        self._active = True

    def stop(self) -> None:
        self._active = False

    def health(self) -> ConnectorHealth:
        if not self._active:
            return ConnectorHealth(state=ConnectorState.STOPPED)
        if self._last_error is not None:
            return ConnectorHealth(state=ConnectorState.DEGRADED, message=self._last_error)
        age_s = None
        if self._last_poll_monotonic is not None:
            age_s = max(0.0, time.monotonic() - self._last_poll_monotonic)
        return ConnectorHealth(
            state=ConnectorState.RUNNING, last_sample_age_s=age_s,
            details={'worker_url': self._worker_url or ''},
        )

    def poll(self) -> list[Prediction]:
        if not self._active or self._sensor_id is None or self._worker_url is None:
            return []
        try:
            response = self._fetch_latest()
        except Exception as e:
            # Still re-raised - see module docstring, _poll_raw() isolation is unchanged - but
            # self._last_error is set first so this plugin's *own* health() (called independently
            # of poll(), possibly on a completely different schedule) also reflects the failure.
            # Found live-verifying issue #126's core-wrapper self-healing fix: without this, this
            # plugin's health() kept reporting RUNNING after a poll() failure (its own _last_error
            # was never touched by a propagated exception), silently overwriting the wrapper's own
            # correctly-DEGRADED state the next time health() happened to be called.
            self._last_error = str(e)
            raise
        self._last_poll_monotonic = time.monotonic()
        self._last_error = None

        frame_timestamp_ms = response.get('frame_timestamp_ms')
        detections = response.get('detections')
        if not isinstance(frame_timestamp_ms, (int, float)) or isinstance(frame_timestamp_ms, bool) \
                or not isinstance(detections, list):
            self._last_error = (
                "worker response missing a numeric 'frame_timestamp_ms' or a list 'detections'"
            )
            return []
        if frame_timestamp_ms == self._last_seen_frame_timestamp_ms:
            return []  # same frame as last poll - nothing new to emit
        self._last_seen_frame_timestamp_ms = frame_timestamp_ms

        return [Prediction(
            # Includes session_id, not just sensor_id/source_id/timestamp_ms (issue #123's own
            # phrasing) - `predictions.id` is a single global primary key
            # (backend/app/persistence/migrations/0001_initial.sql), not scoped per session. A
            # recorded replay that loops back to timestamp 0 in a *second* session would otherwise
            # collide with session one's own rows and be silently dropped by
            # insert_batch_with_partial_failure's duplicate-id handling - real data loss, not a
            # harmless dedup. Within one session, worker-restart/loop dedup still works exactly as
            # intended since session_id stays constant.
            id=f'{PLUGIN_ID}:{self._session_id}:{self._sensor_id}:{frame_timestamp_ms}',
            session_id=self._session_id, timestamp_ms=float(frame_timestamp_ms),
            source_id=f'{self._sensor_id}.yolo_bridge', sensor_ids=[self._sensor_id],
            task=self._task, value={'detections': detections},
            metadata={'worker_url': self._worker_url},
        )]

    def _fetch_latest(self) -> dict[str, Any]:
        request = urllib.request.Request(f'{self._worker_url}/latest')
        with urllib.request.urlopen(request, timeout=self._timeout_s) as response:  # noqa: S310 - operator-supplied local worker_url, not user input
            return json.loads(response.read())


def create() -> YoloBridgeConnector:
    """The entry-point factory - `multisens.plugins` resolves to this
    zero-arg callable, called once per discovery pass."""
    return YoloBridgeConnector()
