"""Bridges ROS diagnostics/sync topics into plain JSON-serializable dicts.

Runs an rclpy node in a background thread (kept separate from FastAPI's
async event loop - rclpy.spin() blocks, so it can't share a thread with
uvicorn). The browser never sees a ROS message type: DiagnosticStatus/
KeyValue get flattened into a plain dict here, once, in the one place that
understands ROS message shapes. REST/WebSocket handlers only ever touch the
translated snapshot() result.

This is a genuinely separate container from `ros` (see docker-compose.yml),
so this is the first place in the codebase where DDS discovery has to work
*across* containers rather than between processes inside one container -
verified directly, not assumed, same standard applied to the earlier
same-container case in Phase 1.
"""
import threading
from typing import Optional

import rclpy
from diagnostic_msgs.msg import DiagnosticArray, DiagnosticStatus
from rclpy.node import Node

_LEVEL_NAMES = {
    DiagnosticStatus.OK: 'ok',
    DiagnosticStatus.WARN: 'warn',
    DiagnosticStatus.ERROR: 'error',
    DiagnosticStatus.STALE: 'stale',
}


def _level_name(level: bytes) -> str:
    return _LEVEL_NAMES.get(level, 'unknown')


def _status_to_dict(status: DiagnosticStatus) -> dict:
    return {
        'level': _level_name(status.level),
        'message': status.message,
        **{kv.key: kv.value for kv in status.values},
    }


class RosBridge:
    def __init__(self):
        self._lock = threading.Lock()
        self._sensors: dict[str, dict] = {}
        self._system: Optional[dict] = None
        self._sync: Optional[dict] = None
        self._node: Optional[Node] = None
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self):
        self._thread.start()

    def snapshot(self) -> dict:
        with self._lock:
            return {
                'sensors': dict(self._sensors),
                'system': self._system,
                'sync': self._sync,
            }

    def _run(self):
        rclpy.init()
        node = Node('multisens_backend_bridge')
        self._node = node
        node.create_subscription(
            DiagnosticArray, '/multisens/diagnostics', self._on_diagnostics, 10)
        node.create_subscription(
            DiagnosticArray, '/multisens/sync/status', self._on_sync, 10)
        rclpy.spin(node)

    def _on_diagnostics(self, msg: DiagnosticArray):
        with self._lock:
            for status in msg.status:
                entry = _status_to_dict(status)
                if status.hardware_id == 'system':
                    self._system = entry
                else:
                    self._sensors[status.hardware_id] = entry

    def _on_sync(self, msg: DiagnosticArray):
        with self._lock:
            for status in msg.status:
                if status.hardware_id == 'sync':
                    self._sync = _status_to_dict(status)
