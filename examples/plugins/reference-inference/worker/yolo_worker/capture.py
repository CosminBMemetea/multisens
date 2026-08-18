"""RTSP capture + YOLOv8n inference loop - the only module in this
package that imports `cv2`/`ultralytics`, kept isolated so
`state.py`/`server.py`/`detections.py` (and their tests) never need
those heavy runtime deps installed. Opens its own independent RTSP
connection to the target sensor - the same "N independent readers of
one RTSP source" pattern `backend/app/video_relay.py` and
`ros2_ws`'s `rtsp_ingestion_node` already establish (issue #123).

Timestamp honesty: `frame_timestamp_ms` below is this worker's own
wall-clock reading at frame-read time - not a true RTSP/source capture
timestamp. Documented at the same honesty tier `docs/topics.md`
already holds `frame_stamp` to (issue #123, point 5) - no better
timestamp exists anywhere in this pipeline to inherit.

Decoder log noise: looping a recorded file through RTSP with
`ffmpeg -stream_loop -1 -c copy` (the reference replay technique this
project's own docs use for testing without a live camera) produces a
genuinely discontinuous H.264 bitstream at each loop boundary - no
re-encode means no clean keyframe at the seam, so libavcodec logs
`error while decoding MB...`/`co located POCs unavailable`/`mmco:
unref short failure` for a frame or two before recovering on its own.
Harmless (confirmed: FPS and detections both keep flowing across the
seam) but was drowning out this worker's own log output. Quieted by
default via `OPENCV_FFMPEG_LOGLEVEL` below - set that env var yourself
before running this worker to see the raw decoder output again (e.g.
while debugging an actual RTSP source, not a looped demo file).
"""
from __future__ import annotations

import os
import threading
import time
from typing import Any

# Must be set before `import cv2` - OpenCV's FFmpeg backend reads this at
# capture-open time, not lazily. `setdefault` so a value already set in
# the environment (e.g. by an operator who wants the raw decoder output)
# is never overridden. '8' = FFmpeg's own AV_LOG_FATAL - quiet enough to
# hide the loop-boundary noise above without hiding a decoder crash.
os.environ.setdefault('OPENCV_FFMPEG_LOGLEVEL', '8')

import cv2
from ultralytics import YOLO

from yolo_worker.detections import CLASS_NAME_BY_ID, DEFAULT_CONFIDENCE_THRESHOLD, build_detections
from yolo_worker.state import SharedState


def _extract_boxes(result: Any) -> list[tuple[int, float, float, float, float, float]]:
    """Reduces one `ultralytics.engine.results.Results` object down to
    plain `(class_id, confidence, x1, y1, x2, y2)` tuples - the
    model-library-agnostic shape `detections.build_detections()` (a
    zero-`ultralytics`-dependency module) expects."""
    boxes = []
    if result.boxes is None:
        return boxes
    for box in result.boxes:
        class_id = int(box.cls[0])
        confidence = float(box.conf[0])
        x1, y1, x2, y2 = (float(v) for v in box.xyxy[0])
        boxes.append((class_id, confidence, x1, y1, x2, y2))
    return boxes


def run_capture_loop(
    rtsp_url: str, state: SharedState, *, model_path: str = 'yolov8n.pt',
    confidence_threshold: float = DEFAULT_CONFIDENCE_THRESHOLD,
    reconnect_delay_s: float = 2.0, stop_event: threading.Event | None = None,
) -> None:
    """Runs until `stop_event` is set - one independent RTSP reader,
    reconnecting on any read/open failure rather than exiting, since a
    transient RTSP/decode hiccup must never take the whole worker
    process down (the same discipline `rtsp_ingestion_node` already
    holds itself to for the ROS side of this same RTSP source)."""
    model = YOLO(model_path)
    class_ids = list(CLASS_NAME_BY_ID)
    while stop_event is None or not stop_event.is_set():
        # TCP transport, matching video_relay.py's own '-rtsp_transport tcp'
        # choice - UDP drops frames badly on the Docker/host networking path
        # this project already targets.
        capture = cv2.VideoCapture(rtsp_url, cv2.CAP_FFMPEG)
        if not capture.isOpened():
            state.record_error(f"could not open RTSP stream '{rtsp_url}'")
            capture.release()
            time.sleep(reconnect_delay_s)
            continue
        try:
            while stop_event is None or not stop_event.is_set():
                ok, frame = capture.read()
                if not ok or frame is None:
                    state.record_error('RTSP read failed - reconnecting')
                    break
                frame_timestamp_ms = time.time() * 1000.0
                height, width = frame.shape[:2]
                results = model.predict(frame, classes=class_ids, conf=confidence_threshold, verbose=False)
                boxes = _extract_boxes(results[0]) if results else []
                detections = build_detections(boxes, width, height, confidence_threshold=confidence_threshold)
                state.record_frame(frame_timestamp_ms, detections)
        finally:
            capture.release()
        if stop_event is None or not stop_event.is_set():
            time.sleep(reconnect_delay_s)
