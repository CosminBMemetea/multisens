"""Phase 1 placeholder subscriber.

Stands in for a downstream consumer (sync/diagnostics) so Phase 1 can prove
cross-node DDS delivery works before any real subscribers exist.
"""
import rclpy
from rclpy.node import Node
from std_msgs.msg import String


class PlaceholderListener(Node):
    def __init__(self):
        super().__init__('placeholder_listener')
        self.create_subscription(
            String, '/multisens/_phase1/graph_check', self._on_message, 10)

    def _on_message(self, msg: String):
        self.get_logger().info(f'received: {msg.data}')


def main(args=None):
    rclpy.init(args=args)
    node = PlaceholderListener()
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
