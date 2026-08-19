"""RTSP capture + MediaPipe face detection loop - the only module in
this package that imports cv2/mediapipe, kept isolated so
detections.py (and its tests) never need those heavy runtime deps
installed. Opens its own independent RTSP connection to the target
sensor - same pattern yolo_worker's/emotion_worker's own capture.py
already establish. Imports `SharedState`/`log` directly from
`multisens_worker_kit` (issue #141/#142) - unlike its two siblings,
this package never had its own duplicated state.py/server.py/log.py to
begin with, so there's nothing to re-export.

Face detection: MediaPipe Tasks API `FaceDetector`
(`blaze_face_short_range.tflite`, downloaded separately - see this
package's own README, same "don't commit model weights" convention as
yolov8n.pt/emotion-ferplus-8.onnx). Multi-face, unlike the emotion
worker's deliberate single-face scope - MediaPipe's own detector
returns every face it finds, and there's no reason to discard extras
here.

**A real, reproduced environment finding (issue #142)**: mediapipe
1.0.1 crashes with a fatal `Check failed: service_ Service is
unavailable` inside `TensorsToDetectionsCalculator` on this machine
(macOS/Apple Silicon) - reproduced twice, including with
`delegate=CPU` explicitly forced, so it isn't a GPU-delegate opt-out
problem. `mediapipe==0.10.21` (`requirements.txt`) does not have this
bug - confirmed working end to end (real face, real bounding box, real
confidence) before this worker was written. `delegate=CPU` is still
requested explicitly below, matching this project's "CPU by default,
report what's actually resolved, never assume GPU" posture (RideSafe
bring-up already found `ultralytics` doesn't auto-use Apple's MPS
either) - MediaPipe's Tasks API doesn't expose a "which delegate did it
actually use" query, so unlike onnxruntime's `get_providers()` there is
nothing more honest to report back here than the request itself.

Timestamp honesty and decoder-noise quieting: same posture as the
sibling workers' own capture.py.
"""
from __future__ import annotations

import os
import threading
import time

os.environ.setdefault('OPENCV_FFMPEG_LOGLEVEL', '8')

import cv2
import mediapipe as mp
from mediapipe.tasks import python as mp_python
from mediapipe.tasks.python import vision as mp_vision
from multisens_worker_kit.log import make_logger
from multisens_worker_kit.state import SharedState

from mediapipe_worker.detections import DEFAULT_CONFIDENCE_THRESHOLD, build_detections

log = make_logger('mediapipe_worker')

DEFAULT_TARGET_INFERENCE_FPS = 10.0


def _create_detector(model_path: str) -> mp_vision.FaceDetector:
    base_options = mp_python.BaseOptions(
        model_asset_path=model_path, delegate=mp_python.BaseOptions.Delegate.CPU,
    )
    options = mp_vision.FaceDetectorOptions(base_options=base_options)
    return mp_vision.FaceDetector.create_from_options(options)


def run_capture_loop(
    rtsp_url: str, state: SharedState, *, worker_id: str, sensor_id: str,
    model_path: str, confidence_threshold: float = DEFAULT_CONFIDENCE_THRESHOLD,
    target_inference_fps: float = DEFAULT_TARGET_INFERENCE_FPS,
    reconnect_delay_s: float = 2.0, stop_event: threading.Event | None = None,
) -> None:
    """Runs until `stop_event` is set - one independent RTSP reader,
    reconnecting on any read/open failure rather than exiting (same
    discipline as every other capture loop in this project).

    `target_inference_fps` throttles the detect path - found necessary
    live for the sibling emotion worker's own Haar+ONNX pipeline (issue
    #136, 300%->59.5% CPU at 6fps); BlazeFace short-range is a smaller,
    purpose-built mobile model, measured lighter per call, so this
    starts at a higher default (10fps) - not assumed identical to the
    other two workers' own tuned values. Every frame is still read
    (draining the RTSP buffer so it never backs up), just not all of
    them are processed."""
    log('info', 'model_loading', worker_id=worker_id, sensor_id=sensor_id, model=model_path)
    try:
        detector = _create_detector(model_path)
    except Exception as e:
        log('error', 'model_load_failed', worker_id=worker_id, sensor_id=sensor_id, model=model_path,
            exception_type=type(e).__name__, exception_message=str(e))
        raise
    log('info', 'model_loaded', worker_id=worker_id, sensor_id=sensor_id, model=model_path)

    while stop_event is None or not stop_event.is_set():
        capture = cv2.VideoCapture(rtsp_url, cv2.CAP_FFMPEG)
        if not capture.isOpened():
            state.record_error(f"could not open RTSP stream '{rtsp_url}'")
            log('warning', 'input_connect_failed', rate_limit_s=10.0,
                worker_id=worker_id, sensor_id=sensor_id, rtsp_url=rtsp_url)
            capture.release()
            time.sleep(reconnect_delay_s)
            continue
        log('info', 'input_connected', worker_id=worker_id, sensor_id=sensor_id, rtsp_url=rtsp_url)
        inference_started_logged = False
        min_interval_s = 1.0 / target_inference_fps if target_inference_fps > 0 else 0.0
        last_processed_monotonic: float | None = None
        try:
            while stop_event is None or not stop_event.is_set():
                ok, frame = capture.read()
                if not ok or frame is None:
                    state.record_error('RTSP read failed - reconnecting')
                    log('warning', 'input_disconnected', rate_limit_s=10.0,
                        worker_id=worker_id, sensor_id=sensor_id, rtsp_url=rtsp_url)
                    break
                now = time.monotonic()
                if last_processed_monotonic is not None and now - last_processed_monotonic < min_interval_s:
                    continue  # read to drain the buffer, but skip the expensive path this frame
                last_processed_monotonic = now
                frame_timestamp_ms = time.time() * 1000.0
                height, width = frame.shape[:2]
                try:
                    rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb_frame)
                    result = detector.detect(mp_image)
                    faces = [
                        (
                            d.categories[0].score, d.bounding_box.origin_x, d.bounding_box.origin_y,
                            d.bounding_box.width, d.bounding_box.height,
                        )
                        for d in result.detections
                    ]
                except Exception as e:
                    state.record_error(f'inference failed: {e}')
                    log('error', 'inference_exception', rate_limit_s=5.0,
                        worker_id=worker_id, sensor_id=sensor_id,
                        exception_type=type(e).__name__, exception_message=str(e))
                    continue
                if not inference_started_logged:
                    log('info', 'inference_started', worker_id=worker_id, sensor_id=sensor_id)
                    inference_started_logged = True
                detections = build_detections(
                    faces, width, height, confidence_threshold=confidence_threshold,
                )
                state.record_frame(frame_timestamp_ms, detections)
        finally:
            capture.release()
            log('info', 'inference_stopped', worker_id=worker_id, sensor_id=sensor_id)
        if stop_event is None or not stop_event.is_set():
            log('info', 'reconnecting', rate_limit_s=10.0,
                worker_id=worker_id, sensor_id=sensor_id, delay_s=reconnect_delay_s)
            time.sleep(reconnect_delay_s)
