"""A thin `PredictionConnector` bridge - sibling to
multisens_reference_inference's own yolo_bridge, byte-for-byte the same
architecture: polls a separately-running inference worker process's
small local HTTP endpoint (see the sibling `worker/` directory) and
translates its latest detection into canonical `Prediction` objects.
Owns zero ML dependency itself. The actual face-detection + FER+
classification model and its RTSP reader live in a genuinely separate
OS process, so a native-level crash there can never take down this
plugin or the MultiSens backend process it's loaded into - identical
process-isolation reasoning to the vehicle-detection bridge this
mirrors.

Not a driver-monitoring system, not an NCAP/DMS compliance claim, not a
clinical or psychological assessment of emotion - a pretrained model's
classification, wired through the exact same architecture as the
RideSafe vehicle-detection demo, for architecture demonstration only.

Staleness handling, error logging, dedup-on-unchanged-timestamp: all
identical reasoning to yolo_bridge.py (issues #126/#127) - not
re-derived here, just re-applied.
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

PLUGIN_ID = 'multisens.reference.inference.emotion_bridge'
HOMEPAGE = 'https://github.com/CosminBMemetea/multisens/tree/main/examples/plugins/reference-inference-emotion'

SUPPORTED_MODALITIES = ('rgb',)
DEFAULT_TASK = 'facial_emotion'
DEFAULT_TIMEOUT_S = 2.0
DEFAULT_STALE_AFTER_S = 5.0
EMOTION_CLASSES = ['neutral', 'happiness', 'surprise', 'sadness', 'anger', 'disgust', 'fear', 'contempt']


class EmotionBridgeConnector:
    def __init__(self) -> None:
        self._session_id: str | None = None
        self._sensor_id: str | None = None
        self._worker_url: str | None = None
        self._task = DEFAULT_TASK
        self._timeout_s = DEFAULT_TIMEOUT_S
        self._stale_after_s = DEFAULT_STALE_AFTER_S
        self._active = False
        self._last_seen_frame_timestamp_ms: float | None = None
        self._last_advance_monotonic: float | None = None
        self._last_error: str | None = None
        # Dashboard-facing summary of the last genuinely new frame's
        # detections - derived from the same already class/confidence-
        # filtered (0-or-1-length) list poll() already emits, no second
        # copy of any threshold logic.
        self._last_detections: list[dict[str, Any]] = []

    def descriptor(self) -> PluginDescriptor:
        return PluginDescriptor(
            plugin_id=PLUGIN_ID, name='FER+ Facial Emotion Classification Bridge', version='0.1.0',
            plugin_type=PluginType.PREDICTION_CONNECTOR, api_version=MULTISENS_PLUGIN_API_VERSION,
            capabilities={
                'supported_modalities': list(SUPPORTED_MODALITIES),
                'model': 'emotion-ferplus',
                'classes': list(EMOTION_CLASSES),
                'confidence_threshold': 0.40,
            },
            author='MultiSens Project', license='Apache-2.0', homepage=HOMEPAGE,
            description=(
                'Thin bridge to a separately-running face-detection + FER+ emotion-classification '
                'worker (see the sibling worker/ directory) - zero ML dependency itself, '
                'process-isolated from the actual model. Not a driver-monitoring or NCAP/DMS system.'
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
        top = self._last_detections[0] if self._last_detections else None
        details: dict[str, Any] = {
            'worker_url': self._worker_url or '',
            'face_present': top is not None,
            'top_emotion': top['label'] if top else None,
            'top_confidence': top['confidence'] if top else None,
        }
        if self._last_advance_monotonic is None:
            return ConnectorHealth(state=ConnectorState.RUNNING, last_sample_age_s=None, details=details)
        age_s = max(0.0, time.monotonic() - self._last_advance_monotonic)
        if age_s > self._stale_after_s:
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
            self._last_error = str(e)
            print(f'emotion_bridge: sensor_id={self._sensor_id!r} poll failed: {type(e).__name__}: {e}')
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
            return []
        self._last_seen_frame_timestamp_ms = frame_timestamp_ms
        self._last_advance_monotonic = time.monotonic()
        self._last_detections = detections

        return [Prediction(
            id=f'{PLUGIN_ID}:{self._session_id}:{self._sensor_id}:{frame_timestamp_ms}',
            session_id=self._session_id, timestamp_ms=float(frame_timestamp_ms),
            source_id=f'{self._sensor_id}.emotion_bridge', sensor_ids=[self._sensor_id],
            task=self._task, value={'detections': detections},
            metadata={'worker_url': self._worker_url},
        )]

    def _fetch_latest(self) -> dict[str, Any]:
        request = urllib.request.Request(f'{self._worker_url}/latest')
        with urllib.request.urlopen(request, timeout=self._timeout_s) as response:  # noqa: S310 - operator-supplied local worker_url, not user input
            return json.loads(response.read())


def create() -> EmotionBridgeConnector:
    """The entry-point factory - `multisens.plugins` resolves to this
    zero-arg callable, called once per discovery pass."""
    return EmotionBridgeConnector()
