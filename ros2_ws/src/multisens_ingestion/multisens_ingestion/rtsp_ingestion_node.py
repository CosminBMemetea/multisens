"""Generic RTSP-to-ROS ingestion node.

Opens one RTSP source and publishes sensor_msgs/Image on
/multisens/sensors/{modality}/image_raw. Identity (sensor_id, modality,
source_type, url) is configured entirely via ROS parameters so the same
node handles any sensor — no per-sensor subclassing.

Phase 2 scope: one instantiation, RGB, launch-hardcoded parameters, basic
reconnect-on-failure. Phase 3 generalizes this to N instantiations driven by
config/sensors.yaml. Diagnostics (Phase 4) and sync (Phase 5) are separate,
not duplicated here.
"""
import time

import cv2
import rclpy
from cv_bridge import CvBridge
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import Image

RECONNECT_BACKOFF_SEC = 2.0
LOG_EVERY_N_FRAMES = 90


class RtspIngestionNode(Node):
    def __init__(self):
        super().__init__('rtsp_ingestion_node')

        self.declare_parameter('sensor_id', 'rgb')
        self.declare_parameter('modality', 'rgb')
        self.declare_parameter('source_type', 'physical')
        self.declare_parameter('rtsp_url', 'rtsp://host.docker.internal:8554/rgb')

        self._sensor_id = self.get_parameter('sensor_id').value
        self._modality = self.get_parameter('modality').value
        self._source_type = self.get_parameter('source_type').value
        self._rtsp_url = self.get_parameter('rtsp_url').value

        if self._source_type not in ('physical', 'simulated'):
            raise ValueError(
                f"source_type must be 'physical' or 'simulated', got '{self._source_type}'")

        topic = f'/multisens/sensors/{self._modality}/image_raw'
        self._publisher = self.create_publisher(Image, topic, qos_profile_sensor_data)
        self._bridge = CvBridge()
        self._capture = None
        self._frame_count = 0

        self.get_logger().info(
            f"ingesting sensor_id={self._sensor_id} modality={self._modality} "
            f"source_type={self._source_type} url={self._rtsp_url} -> {topic}")

        self._open_capture()

    def run(self):
        while rclpy.ok():
            self._capture_and_publish_once()
            rclpy.spin_once(self, timeout_sec=0.0)

    def _open_capture(self):
        self.get_logger().info(f'opening RTSP source: {self._rtsp_url}')
        capture = cv2.VideoCapture(self._rtsp_url, cv2.CAP_FFMPEG)
        if capture.isOpened():
            self._capture = capture
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

        self._frame_count += 1
        if self._frame_count % LOG_EVERY_N_FRAMES == 0:
            self.get_logger().info(
                f'{self._sensor_id}: published {self._frame_count} frames '
                f'({frame.shape[1]}x{frame.shape[0]})')

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
