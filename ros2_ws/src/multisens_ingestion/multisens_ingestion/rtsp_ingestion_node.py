"""Generic RTSP-to-ROS ingestion node.

Opens one RTSP source and publishes sensor_msgs/Image on
/multisens/sensors/{modality}/image_raw. Identity (sensor_id, modality,
source_type, url) is configured entirely via ROS parameters so the same
node handles any sensor — no per-sensor subclassing.

Also self-publishes its own diagnostic_msgs/DiagnosticArray on
/multisens/diagnostics. This node is the only thing that genuinely knows
connection_state, reconnect_count, and real resolution/encoding - a
passive external subscriber could only guess at those, so diagnostics is
self-reported here rather than computed by a separate node watching the
image topic. Global diagnostics (CPU/RAM/uptime/sensor count), which no
single sensor owns, are a separate node - see multisens_diagnostics.

Also publishes sensor_msgs/TimeReference on
/multisens/sensors/{modality}/frame_stamp, carrying the same header as the
Image message with no pixel payload. Added for Phase 5 (multisens_sync)
after measuring that a subscriber processing three concurrent ~900KB raw
Image topics at 30fps couldn't keep up well enough to measure real
cross-sensor skew (see multisens_sync) - consumers that only need timing,
not pixels, should use this instead of image_raw. TimeReference specifically
(not a bare std_msgs/Header) because message_filters.ApproximateTimeSynchronizer
expects a message with a *nested* header.stamp - a bare Header only has
.stamp directly and silently never matches anything (found by testing: 0
synchronized groups, ever, with a bare Header - not an error, just nothing).

Phase 2 scope: one instantiation, RGB, launch-hardcoded parameters, basic
reconnect-on-failure. Phase 3 generalized this to N instantiations driven by
config/sensors.yaml. Phase 4 added the self-diagnostics described above.
Phase 5 added the frame_stamp topic described above.
"""
import time

import cv2
import rclpy
from cv_bridge import CvBridge
from diagnostic_msgs.msg import DiagnosticArray, DiagnosticStatus, KeyValue
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import Image, TimeReference

RECONNECT_BACKOFF_SEC = 2.0
LOG_EVERY_N_FRAMES = 90
DIAGNOSTICS_PERIOD_SEC = 1.0


class RtspIngestionNode(Node):
    def __init__(self):
        super().__init__('rtsp_ingestion_node')

        self.declare_parameter('sensor_id', 'rgb')
        self.declare_parameter('modality', 'rgb')
        self.declare_parameter('source_type', 'physical')
        self.declare_parameter('rtsp_url', '')
        self.declare_parameter('expected_fps', -1.0)

        self._sensor_id = self.get_parameter('sensor_id').value
        self._modality = self.get_parameter('modality').value
        self._source_type = self.get_parameter('source_type').value
        self._rtsp_url = self.get_parameter('rtsp_url').value
        self._expected_fps = self.get_parameter('expected_fps').value

        if self._source_type not in ('physical', 'simulated'):
            raise ValueError(
                f"source_type must be 'physical' or 'simulated', got '{self._source_type}'")
        if not self._rtsp_url:
            # No default here on purpose: this node is generic and must not
            # bake in any particular host or sensor simulator's address.
            raise ValueError("rtsp_url parameter is required and was not set")

        topic = f'/multisens/sensors/{self._modality}/image_raw'
        self._publisher = self.create_publisher(Image, topic, qos_profile_sensor_data)
        stamp_topic = f'/multisens/sensors/{self._modality}/frame_stamp'
        self._stamp_publisher = self.create_publisher(
            TimeReference, stamp_topic, qos_profile_sensor_data)
        self._diagnostics_pub = self.create_publisher(DiagnosticArray, '/multisens/diagnostics', 10)
        self._bridge = CvBridge()
        self._capture = None
        self._frame_count = 0

        self._had_ever_opened = False
        self._reconnect_count = 0
        self._last_frame_monotonic = None
        self._last_resolution = None
        self._last_publish_latency_ms = None
        self._window_frame_count = 0
        self._window_start_monotonic = time.monotonic()

        self.get_logger().info(
            f"ingesting sensor_id={self._sensor_id} modality={self._modality} "
            f"source_type={self._source_type} url={self._rtsp_url} -> {topic}")

        self._open_capture()
        self.create_timer(DIAGNOSTICS_PERIOD_SEC, self._publish_diagnostics)

    def run(self):
        while rclpy.ok():
            self._capture_and_publish_once()
            rclpy.spin_once(self, timeout_sec=0.0)

    def _open_capture(self):
        self.get_logger().info(f'opening RTSP source: {self._rtsp_url}')
        capture = cv2.VideoCapture(self._rtsp_url, cv2.CAP_FFMPEG)
        if capture.isOpened():
            self._capture = capture
            if self._had_ever_opened:
                self._reconnect_count += 1
            self._had_ever_opened = True
            self.get_logger().info('RTSP source opened')
        else:
            capture.release()
            self._capture = None
            self.get_logger().warning(
                f'failed to open {self._rtsp_url}, retrying in {RECONNECT_BACKOFF_SEC}s')

    def _capture_and_publish_once(self):
        if self._capture is None:
            time.sleep(RECONNECT_BACKOFF_SEC)
            self._open_capture()
            return

        ok, frame = self._capture.read()
        read_done = time.monotonic()
        if not ok:
            self.get_logger().warning(
                f'lost RTSP source {self._rtsp_url}, will attempt reconnect')
            self._capture.release()
            self._capture = None
            return

        msg = self._bridge.cv2_to_imgmsg(frame, encoding='bgr8')
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.header.frame_id = f'multisens_{self._sensor_id}'
        self._publisher.publish(msg)

        time_ref_msg = TimeReference()
        time_ref_msg.header = msg.header
        time_ref_msg.time_ref = msg.header.stamp
        time_ref_msg.source = self._sensor_id
        self._stamp_publisher.publish(time_ref_msg)

        self._last_publish_latency_ms = (time.monotonic() - read_done) * 1000.0
        self._last_frame_monotonic = read_done
        self._last_resolution = (frame.shape[1], frame.shape[0])
        self._frame_count += 1
        self._window_frame_count += 1

        if self._frame_count % LOG_EVERY_N_FRAMES == 0:
            self.get_logger().info(
                f'{self._sensor_id}: published {self._frame_count} frames '
                f'({frame.shape[1]}x{frame.shape[0]})')

    def _publish_diagnostics(self):
        now = time.monotonic()
        elapsed = now - self._window_start_monotonic
        fps_received = self._window_frame_count / elapsed if elapsed > 0 else 0.0
        self._window_frame_count = 0
        self._window_start_monotonic = now

        connected = self._capture is not None

        if self._last_frame_monotonic is None:
            last_frame_age_ms = 'unavailable'
        else:
            last_frame_age_ms = f'{(now - self._last_frame_monotonic) * 1000:.0f}'

        status = DiagnosticStatus()
        status.name = f'multisens: {self._sensor_id}'
        status.hardware_id = self._sensor_id
        status.level = DiagnosticStatus.OK if connected else DiagnosticStatus.ERROR
        status.message = (
            'connected' if connected
            else f'disconnected, retrying every {RECONNECT_BACKOFF_SEC:.0f}s')
        status.values = [
            KeyValue(key='modality', value=self._modality),
            KeyValue(key='source_type', value=self._source_type),
            KeyValue(key='connection_state', value='connected' if connected else 'disconnected'),
            KeyValue(key='fps_received', value=f'{fps_received:.1f}'),
            KeyValue(
                key='fps_expected',
                value=f'{self._expected_fps:.1f}' if self._expected_fps >= 0 else 'unavailable'),
            KeyValue(
                key='resolution',
                value=f'{self._last_resolution[0]}x{self._last_resolution[1]}'
                if self._last_resolution else 'unavailable'),
            KeyValue(key='encoding', value='bgr8' if self._last_resolution else 'unavailable'),
            KeyValue(key='frames_received', value=str(self._frame_count)),
            KeyValue(key='frames_dropped', value='unavailable'),
            KeyValue(key='last_frame_age_ms', value=last_frame_age_ms),
            KeyValue(key='reconnect_count', value=str(self._reconnect_count)),
            KeyValue(
                key='publish_latency_ms',
                value=f'{self._last_publish_latency_ms:.2f}'
                if self._last_publish_latency_ms is not None else 'unavailable'),
        ]

        msg = DiagnosticArray()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.status = [status]
        self._diagnostics_pub.publish(msg)

    def destroy_node(self):
        if self._capture is not None:
            self._capture.release()
        super().destroy_node()


def main(args=None):
    rclpy.init(args=args)
    node = RtspIngestionNode()
    try:
        node.run()
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
