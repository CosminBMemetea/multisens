"""RTSP capture + face detection + FER+ emotion classification loop -
the only module in this package that imports cv2/onnxruntime, kept
isolated so state.py/server.py/detections.py (and their tests) never
need those heavy runtime deps installed. Opens its own independent RTSP
connection to the target sensor - same pattern yolo_worker's own
capture.py already establishes.

Face detection: OpenCV's bundled Haar cascade (`haarcascade_frontalface_
default.xml`, ships with opencv-python itself, no separate download) -
picks the *largest* detected face if more than one, since this is a
single-subject reference demo, not a multi-face system. Classification:
the emotion-ferplus ONNX model (Microsoft/ONNX Model Zoo, 8-class,
64x64 grayscale input) via onnxruntime - CPU, matching this project's
own "measure, don't assume GPU" discipline (RideSafe bring-up found
`ultralytics` doesn't auto-use Apple's MPS either).

Timestamp honesty and decoder-noise quieting: same posture as
yolo_worker's own capture.py - `frame_timestamp_ms` is this worker's own
wall-clock read time, and `OPENCV_FFMPEG_LOGLEVEL` is quieted the same
way (relevant if this worker is ever pointed at a looped recorded file
instead of a live webcam).

Exception handling around the classification call is deliberate from
the start here, not added after the fact - yolo_worker's own
`model.predict()` call originally had none at all (a real bug found and
fixed during the RideSafe bring-up, Phase 28) and silently killing this
worker's capture thread on one bad frame would be the same class of gap.
"""
from __future__ import annotations

import os
import threading
import time
from typing import Any

os.environ.setdefault('OPENCV_FFMPEG_LOGLEVEL', '8')

import cv2
import numpy as np
import onnxruntime as ort

from emotion_worker.detections import CLASS_NAME_BY_INDEX, DEFAULT_CONFIDENCE_THRESHOLD, build_detections
from emotion_worker.log import log
from emotion_worker.state import SharedState

MODEL_INPUT_SIZE = 64


def _softmax(logits: np.ndarray) -> np.ndarray:
    shifted = logits - np.max(logits)
    exp = np.exp(shifted)
    return exp / np.sum(exp)


def _largest_face(faces: Any) -> tuple[int, int, int, int] | None:
    if faces is None or len(faces) == 0:
        return None
    return max((tuple(f) for f in faces), key=lambda f: f[2] * f[3])


def _classify_face(
    session: ort.InferenceSession, input_name: str, gray_frame: np.ndarray,
    face_box: tuple[int, int, int, int],
) -> list[float]:
    x, y, w, h = face_box
    face = gray_frame[y:y + h, x:x + w]
    face = cv2.resize(face, (MODEL_INPUT_SIZE, MODEL_INPUT_SIZE))
    input_tensor = face.astype(np.float32).reshape(1, 1, MODEL_INPUT_SIZE, MODEL_INPUT_SIZE)
    logits = session.run(None, {input_name: input_tensor})[0][0]
    return _softmax(logits).tolist()


DEFAULT_TARGET_INFERENCE_FPS = 6.0


def run_capture_loop(
    rtsp_url: str, state: SharedState, *, worker_id: str, sensor_id: str,
    model_path: str, confidence_threshold: float = DEFAULT_CONFIDENCE_THRESHOLD,
    target_inference_fps: float = DEFAULT_TARGET_INFERENCE_FPS,
    reconnect_delay_s: float = 2.0, stop_event: threading.Event | None = None,
) -> None:
    """Runs until `stop_event` is set - one independent RTSP reader,
    reconnecting on any read/open failure rather than exiting (same
    discipline as every other capture loop in this project).

    `target_inference_fps` throttles the expensive face-detect +
    classify path - found necessary live (a real measurement, not
    assumed): unlike YOLOv8n, which is naturally slow enough per frame
    to self-throttle to a few fps, Haar cascade + this small ONNX model
    run fast enough to nearly keep up with a 30fps source with zero
    throttling, driving ~300% sustained CPU on this machine. Every
    frame is still read (draining the RTSP buffer so it never backs
    up - same "latest frame, not a growing queue" policy the RideSafe
    worker already established), just not all of them are processed."""
    log('info', 'model_loading', worker_id=worker_id, sensor_id=sensor_id, model=model_path)
    try:
        session = ort.InferenceSession(model_path)
        input_name = session.get_inputs()[0].name
        face_cascade = cv2.CascadeClassifier(
            cv2.data.haarcascades + 'haarcascade_frontalface_default.xml'  # type: ignore[attr-defined]
        )
        if face_cascade.empty():
            raise RuntimeError('failed to load bundled haarcascade_frontalface_default.xml')
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
                    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                    faces = face_cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(60, 60))
                    face_box = _largest_face(faces)
                    class_probabilities = (
                        _classify_face(session, input_name, gray, face_box) if face_box is not None else None
                    )
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
                    face_box, class_probabilities, width, height,
                    confidence_threshold=confidence_threshold,
                )
                state.record_frame(frame_timestamp_ms, detections)
        finally:
            capture.release()
            log('info', 'inference_stopped', worker_id=worker_id, sensor_id=sensor_id)
        if stop_event is None or not stop_event.is_set():
            log('info', 'reconnecting', rate_limit_s=10.0,
                worker_id=worker_id, sensor_id=sensor_id, delay_s=reconnect_delay_s)
            time.sleep(reconnect_delay_s)
