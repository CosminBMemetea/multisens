"""Thread-safe shared state between an inference worker's capture/inference
thread and its HTTP server thread - the worker's own internal
producer/consumer boundary, deliberately tiny (a lock-guarded snapshot,
nothing event-driven) since the HTTP side only ever needs "whatever the
latest finished frame was," never a queue of history.

Extracted from the reference YOLO/emotion workers (issue #141) - the two
were byte-identical here except for docstrings and had been deliberately
kept as separate copies ("each reference worker is meant to be a
genuinely standalone, independently-installable process"). That reasoning
was correct for two workers; it stops paying for itself at a third
(exactly the "one plugin per model won't scale" problem, applied to the
worker side of the process boundary). Depending on this tiny,
dependency-free package doesn't compromise standalone-ness: nothing here
pulls in cv2/onnxruntime/ultralytics, and each worker is still its own
OS process with its own crash domain - the same "sdk/ is a shared,
dependency-free contract every plugin already depends on without anyone
calling that a violation of plugin independence" precedent.

`detections` stays the field name for now - both proven workers already
emit a class/confidence/bbox-shaped list under this name over the wire,
and renaming it here would be speculative generalization ahead of a
second output shape actually existing. A future worker whose output
isn't detection-shaped (e.g. raw landmarks) can define its own payload
field alongside this generic envelope rather than forcing everything
through one name - see this package's README.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass


@dataclass(frozen=True)
class LatestFrameSnapshot:
    sensor_id: str
    frame_timestamp_ms: float | None       # None until the first frame has been processed
    detections: list[dict]
    frames_processed: int
    last_error: str | None
    last_frame_monotonic: float | None      # for last_frame_age_s - never serialized directly


class SharedState:
    def __init__(self, sensor_id: str) -> None:
        self._sensor_id = sensor_id
        self._lock = threading.Lock()
        self._frame_timestamp_ms: float | None = None
        self._detections: list[dict] = []
        self._frames_processed = 0
        self._last_error: str | None = None
        self._last_frame_monotonic: float | None = None

    def record_frame(self, frame_timestamp_ms: float, detections: list[dict]) -> None:
        with self._lock:
            self._frame_timestamp_ms = frame_timestamp_ms
            self._detections = detections
            self._frames_processed += 1
            self._last_error = None
            self._last_frame_monotonic = time.monotonic()

    def record_error(self, message: str) -> None:
        with self._lock:
            self._last_error = message

    def snapshot(self) -> LatestFrameSnapshot:
        with self._lock:
            return LatestFrameSnapshot(
                sensor_id=self._sensor_id, frame_timestamp_ms=self._frame_timestamp_ms,
                detections=list(self._detections), frames_processed=self._frames_processed,
                last_error=self._last_error, last_frame_monotonic=self._last_frame_monotonic,
            )


def build_latest_payload(snapshot: LatestFrameSnapshot) -> dict:
    return {
        'sensor_id': snapshot.sensor_id,
        'frame_timestamp_ms': snapshot.frame_timestamp_ms,
        'detections': snapshot.detections,
    }


def build_health_payload(snapshot: LatestFrameSnapshot) -> dict:
    age_s = None
    if snapshot.last_frame_monotonic is not None:
        age_s = max(0.0, time.monotonic() - snapshot.last_frame_monotonic)
    return {
        'status': 'ok' if snapshot.frame_timestamp_ms is not None else 'starting',
        'sensor_id': snapshot.sensor_id,
        'frames_processed': snapshot.frames_processed,
        'last_frame_age_s': age_s,
        'last_error': snapshot.last_error,
    }
