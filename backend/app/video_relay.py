"""Per-sensor RTSP-to-MJPEG relay for the browser.

Deliberately independent of ROS: opens its own RTSP connection to the same
URL the ROS ingestion node uses (a second, separate reader - MediaMTX and
most RTSP servers support multiple simultaneous readers of one path), and
never touches the DDS/ROS image topic. This is the Phase 0 architecture
decision that video shouldn't ride through ROS to the browser, made
concrete: verified in Phase 2 that a plain rclpy subscriber can't reliably
keep up with a single raw ~900KB/frame image topic at 30fps, so routing
browser video through ROS would mean re-encoding an already-struggling
stream. This relay instead transcodes directly from RTSP to MJPEG.

Uses ffmpeg's mpjpeg muxer, which natively produces a properly-framed
multipart/x-mixed-replace stream (boundary "ffmpeg" by default) - verified
directly against a live stream before writing this, so it's proxied to the
HTTP client as raw bytes with no manual JPEG frame-boundary parsing needed.

One ffmpeg subprocess per connected HTTP client, started on request and
killed on disconnect - not shared/fanned-out across multiple simultaneous
viewers. Fine for v0.1 (a single dashboard, not a multi-viewer product);
revisit if MultiSens ever needs to support many concurrent browser tabs on
the same sensor.
"""
import subprocess
from typing import Iterator

RELAY_FPS = 15
JPEG_QUALITY = 5  # ffmpeg -q:v scale: 2 (best) - 31 (worst)
READ_CHUNK_BYTES = 4096


def mjpeg_stream(rtsp_url: str) -> Iterator[bytes]:
    cmd = [
        'ffmpeg',
        '-rtsp_transport', 'tcp',
        '-i', rtsp_url,
        '-r', str(RELAY_FPS),
        '-q:v', str(JPEG_QUALITY),
        '-f', 'mpjpeg',
        '-boundary_tag', 'ffmpeg',
        'pipe:1',
    ]
    process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    try:
        while True:
            chunk = process.stdout.read(READ_CHUNK_BYTES)
            if not chunk:
                break
            yield chunk
    finally:
        process.terminate()
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            process.kill()
