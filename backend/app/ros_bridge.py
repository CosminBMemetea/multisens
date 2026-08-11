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

Tracks a last-update timestamp per entry and expires anything older than
STALE_AFTER_SEC out of snapshot(). Found this the hard way in Phase 8: with
no expiry, killing an ingestion node's *process* (not just its RTSP source)
left this bridge repeating that sensor's last message forever - still
"connected", still a fresh fps - because nothing ever arrives to say
otherwise once the publisher itself is gone. system_diagnostics_node and
sync_status_node both already handle exactly this by aging out anything
that stops reporting; this bridge didn't, and needed the same treatment.
"""
import threading
import time
from typing import Optional

import rclpy
from diagnostic_msgs.msg import DiagnosticArray, DiagnosticStatus
from rclpy.node import Node

STALE_AFTER_SEC = 5.0

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
        self._sensors_seen: dict[str, float] = {}
        self._system: Optional[dict] = None
        self._system_seen: Optional[float] = None
        self._sync: Optional[dict] = None
        self._sync_seen: Optional[float] = None
        self._node: Optional[Node] = None
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self):
        self._thread.start()

    def snapshot(self) -> dict:
        now = time.monotonic()
        with self._lock:
            sensors = {
                hardware_id: entry
                for hardware_id, entry in self._sensors.items()
                if now - self._sensors_seen[hardware_id] <= STALE_AFTER_SEC
            }
            system = self._system if self._is_fresh(self._system_seen, now) else None
            sync = self._sync if self._is_fresh(self._sync_seen, now) else None
            return {'sensors': sensors, 'system': system, 'sync': sync}

    @staticmethod
    def _is_fresh(seen: Optional[float], now: float) -> bool:
        return seen is not None and now - seen <= STALE_AFTER_SEC

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
        now = time.monotonic()
        with self._lock:
            for status in msg.status:
                entry = _status_to_dict(status)
                if status.hardware_id == 'system':
                    self._system = entry
                    self._system_seen = now
                else:
                    self._sensors[status.hardware_id] = entry
                    self._sensors_seen[status.hardware_id] = now

    def _on_sync(self, msg: DiagnosticArray):
        now = time.monotonic()
        with self._lock:
            for status in msg.status:
                if status.hardware_id == 'sync':
                    self._sync = _status_to_dict(status)
                    self._sync_seen = now
