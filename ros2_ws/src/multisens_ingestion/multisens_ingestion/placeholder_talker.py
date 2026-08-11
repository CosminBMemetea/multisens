"""Phase 1 placeholder publisher.

Stands in for a real ingestion node so Phase 1 can prove the ROS graph,
launch mechanism, and DDS discovery work before any RTSP logic exists.
Replaced by real per-sensor ingestion nodes in Phase 2/3.
"""
import rclpy
from rclpy.node import Node
from std_msgs.msg import String


class PlaceholderTalker(Node):
    def __init__(self):
        super().__init__('placeholder_talker')
        self._publisher = self.create_publisher(String, '/multisens/_phase1/graph_check', 10)
        self._count = 0
        self.create_timer(1.0, self._tick)

    def _tick(self):
        msg = String()
        msg.data = f'phase1 graph check #{self._count}'
        self._publisher.publish(msg)
        self.get_logger().info(f'published: {msg.data}')
        self._count += 1


def main(args=None):
    rclpy.init(args=args)
    node = PlaceholderTalker()
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
