"""Thread-safe shared state between the capture/inference thread and the
HTTP server thread - identical in shape to yolo_worker's own state.py.
Deliberately generic (a lock-guarded snapshot of "whatever the latest
finished frame was," not a queue of history) - nothing here is
emotion-specific, `detections` is the same class/confidence/bbox shape
either worker produces.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field


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
