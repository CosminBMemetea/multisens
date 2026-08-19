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

**Staleness, not just errors (v1.0-RC, issue #127)**: a worker whose own
video input has died can keep responding to `GET /latest` successfully
forever, just with an unchanging `frame_timestamp_ms` - `poll()` itself
already handles that correctly (dedup, returns `[]`, no exception), but
naively that leaves `health()` reporting `RUNNING` indefinitely for a
feed that's actually been dead for minutes. `last_sample_age_s` here
tracks time since the last frame that genuinely *advanced*, not time
since the last poll *attempt* - a poll that succeeds but sees the same
timestamp again doesn't reset it. Once that staleness exceeds
`stale_after_s`, `health()` reports `DEGRADED` on its own, via a normal
non-raising return - `PredictionConnectorInstance.health()`'s own
adoption logic (issue #126) picks this up exactly the same way it picks
up a plugin's other non-raising `DEGRADED` self-reports, no core-wrapper
change needed.
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
# How long a frame timestamp may go without advancing before a
# technically-successful poll stream counts as stale rather than
# healthy (issue #127) - same order of magnitude as ros_bridge.py's own
# STALE_AFTER_SEC for live sensor diagnostics, not a coincidence: both
# answer "how old is too old to still call this RUNNING."
DEFAULT_STALE_AFTER_S = 5.0


class YoloBridgeConnector:
    def __init__(self) -> None:
        self._session_id: str | None = None
        self._sensor_id: str | None = None
        self._worker_url: str | None = None
        self._task = DEFAULT_TASK
        self._timeout_s = DEFAULT_TIMEOUT_S
        self._stale_after_s = DEFAULT_STALE_AFTER_S
        self._active = False
        self._last_seen_frame_timestamp_ms: float | None = None
        # Wall-clock time this connector last saw frame_timestamp_ms
        # actually change - not the same as "last successful poll()
        # call" (issue #127's own distinction; see module docstring).
        self._last_advance_monotonic: float | None = None
        self._last_error: str | None = None
        # Dashboard-facing summary of the last genuinely new frame's
        # detections (RideSafe bring-up, Phase 12) - deliberately derived
        # from the SAME already class/confidence-filtered list poll()
        # already emits as Prediction.value['detections'] (capture.py's
        # own model.predict(classes=..., conf=...) call already applied
        # both filters), not a second copy of the presence rule. "present"
        # is exactly "the worker returned at least one detection" - no
        # new threshold logic here.
        self._last_detections: list[dict[str, Any]] = []

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
        stale_after_s = config.get('stale_after_s', DEFAULT_STALE_AFTER_S)
        if not isinstance(stale_after_s, (int, float)) or isinstance(stale_after_s, bool) or stale_after_s <= 0:
            raise ConnectorConfigError(f"'stale_after_s' must be a positive number, got {stale_after_s!r}")

        self._session_id = session_id
        self._sensor_id = sensor_id
        self._worker_url = worker_url.rstrip('/')
        self._task = task
        self._timeout_s = float(timeout_s)
        self._stale_after_s = float(stale_after_s)
        self._last_seen_frame_timestamp_ms = None
        self._last_advance_monotonic = None
        self._last_error = None
        self._last_detections = []

    def start(self) -> None:
        self._active = True

    def stop(self) -> None:
        self._active = False

    def health(self) -> ConnectorHealth:
        if not self._active:
            return ConnectorHealth(state=ConnectorState.STOPPED)
        if self._last_error is not None:
            return ConnectorHealth(state=ConnectorState.DEGRADED, message=self._last_error)
        details: dict[str, Any] = {
            'worker_url': self._worker_url or '',
            'vehicle_present': len(self._last_detections) > 0,
            'top_confidence': max((d.get('confidence', 0.0) for d in self._last_detections), default=None),
            # Full detections (label/confidence/bbox), not just the
            # summary fields above - lets a live viewer (dashboard
            # overlay) draw the actual boxes, not just a present/absent
            # badge. Same already-filtered list poll() itself emits as
            # Prediction.value['detections'] - no second copy of any
            # threshold logic, just also surfaced here for anyone polling
            # health() instead of the prediction stream.
            'detections': self._last_detections,
        }
        if self._last_advance_monotonic is None:
            # Never seen a real frame yet - genuinely unknown, not "0s old."
            return ConnectorHealth(state=ConnectorState.RUNNING, last_sample_age_s=None, details=details)
        age_s = max(0.0, time.monotonic() - self._last_advance_monotonic)
        if age_s > self._stale_after_s:
            # issue #127: poll() has kept succeeding (no exception ever
            # reached _poll_raw()), but frame_timestamp_ms hasn't moved -
            # a real, distinguishable-from-"currently seeing nothing"
            # staleness, not a fabricated RUNNING.
            return ConnectorHealth(
                state=ConnectorState.DEGRADED, last_sample_age_s=age_s, details=details,
                message=(
                    f'no new frame from the worker in {age_s:.1f}s '
                    f'(stale_after_s={self._stale_after_s}) - the worker is reachable but its own '
                    f'video input may have stopped advancing'
                ),
            )
        return ConnectorHealth(state=ConnectorState.RUNNING, last_sample_age_s=age_s, details=details)

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
            # RideSafe bring-up, Phase 28 - _poll_raw() (backend/app/plugins/
            # poll_connector_instance.py) catches this and moves the connector
            # to FAILED, but never itself prints anything - without this line,
            # an operator watching the backend's own logs would see nothing
            # at all when inference silently goes DEGRADED/FAILED. Natural
            # rate limit already comes from poll_interval_s (1/s here), no
            # separate throttling needed on top.
            print(f'yolo_bridge: sensor_id={self._sensor_id!r} poll failed: {type(e).__name__}: {e}')
            raise
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
            # Same frame as last poll - nothing new to emit. Deliberately does NOT touch
            # _last_advance_monotonic (issue #127): a run of these is exactly what staleness means.
            return []
        self._last_seen_frame_timestamp_ms = frame_timestamp_ms
        self._last_advance_monotonic = time.monotonic()
        self._last_detections = detections

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
