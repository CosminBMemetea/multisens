"""Cross-sensor timestamp synchronization status.

Subscribes to every configured sensor's /multisens/sensors/{modality}/
frame_stamp topic (sensor_msgs/TimeReference, published by
rtsp_ingestion_node alongside each Image message) via
message_filters.ApproximateTimeSynchronizer - the standard ROS mechanism for
matching messages across topics by timestamp proximity, used here instead of
hand-rolled frame-matching logic - and publishes diagnostic_msgs/DiagnosticArray
on /multisens/sync/status describing current sync health: per-sensor offset
from the group's mean timestamp, max skew within the most recently matched
group, missing/stale sensor state, and matched-group rate.

Deliberately subscribes to frame_stamp, not image_raw: measured directly
that a subscriber processing three concurrent ~900KB raw Image topics at
30fps couldn't keep up, even with a multi-threaded executor (CPython's GIL
means threads don't parallelize the CPU-bound deserialization of large
messages) - synchronized_group_rate_hz stayed near 0-3Hz against a true
~30Hz sensor rate, and reported skew swung wildly (1ms to 460ms) depending
on which messages happened to survive best-effort delivery, an artifact of
the sync node's own processing lag, not real sensor skew. frame_stamp is a
few hundred bytes instead of ~900KB, which fixes this at the source instead
of throwing more threads at it.

TimeReference specifically, not a bare std_msgs/Header: tried a bare Header
first and got exactly 0 synchronized groups, ever - message_filters'
synchronizers read msg.header.stamp internally, which requires a *nested*
header, something a bare Header (which only has .stamp directly) doesn't
have. TimeReference wraps a real header and stays small.

Compares each sensor's ROS *publish* timestamp (msg.header.stamp, set by
rtsp_ingestion_node's own clock at publish time), not a source capture
timestamp - RTSP/H.264 doesn't reliably provide one across independently
read streams, and this repo does not pretend otherwise (see docs/topics.md).

Sync problems are surfaced here, never silently dropped: a sensor that stops
publishing shows up as missing/stale and the affected fields explicitly
report "unavailable" rather than quietly continuing to display the last
known-good numbers as if they were still current.

/multisens/sync/frames (actual grouped/republished synchronized frame
bundles) is out of scope for v0.1 - this node publishes status only.
"""
import os
import time

import message_filters
import rclpy
import yaml
from diagnostic_msgs.msg import DiagnosticArray, DiagnosticStatus, KeyValue
from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import TimeReference

DEFAULT_CONFIG_PATH = '/config/sensors.yaml'
PUBLISH_PERIOD_SEC = 1.0
STALE_AFTER_SEC = 3.0
# How wide a window message_filters itself will accept as "candidate same
# instant" when looking for a match across topics - deliberately generous so
# a failure to find any match doesn't masquerade as a sync problem. The
# actual in-tolerance judgement below uses tolerance_ms, computed from the
# *measured* skew of whatever group was actually found, and can be much
# tighter than this matching window.
MATCHER_SLOP_SEC = 0.5


class SyncStatusNode(Node):
    def __init__(self):
        super().__init__('sync_status_node')

        # Evidence-based, not guessed: measured real max_skew_ms across 10
        # samples on this simulator setup (one physical camera, one ffmpeg
        # process, three independently-read RTSP sessions feeding three
        # co-located ingestion nodes) was 0.2-3.5ms. 25ms leaves ~7-100x
        # headroom above that observed baseline jitter - tight enough to
        # actually mean something, loose enough not to false-positive on
        # normal variation. A physically separate/networked sensor setup
        # would likely show more real skew than this co-located case; revisit
        # this default against real hardware before relying on it there.
        self.declare_parameter('tolerance_ms', 25.0)
        self._tolerance_ms = self.get_parameter('tolerance_ms').value

        config_path = os.environ.get('MULTISENS_SENSORS_CONFIG', DEFAULT_CONFIG_PATH)
        self._modalities = self._load_modalities(config_path)
        if len(self._modalities) < 2:
            self.get_logger().warning(
                f'{len(self._modalities)} sensor(s) configured - synchronization '
                f'needs at least 2 to mean anything')

        self._last_seen_monotonic = {}
        self._last_group_offsets_ms = {}
        self._last_group_max_skew_ms = None
        self._last_group_monotonic = None
        self._window_group_count = 0
        self._window_start_monotonic = time.monotonic()

        # Subscribes to frame_stamp (bare std_msgs/Header), not image_raw -
        # see module docstring for why. Reentrant callback group + a
        # multi-threaded executor (see main()) still used as cheap extra
        # headroom even though header-sized messages alone resolved the
        # measured throughput problem.
        cb_group = ReentrantCallbackGroup()
        subs = []
        for modality in self._modalities:
            topic = f'/multisens/sensors/{modality}/frame_stamp'
            sub = message_filters.Subscriber(
                self, TimeReference, topic, qos_profile=qos_profile_sensor_data,
                callback_group=cb_group)
            sub.registerCallback(self._make_watchdog_cb(modality))
            subs.append(sub)

        self._synchronizer = None
        if subs:
            self._synchronizer = message_filters.ApproximateTimeSynchronizer(
                subs, queue_size=10, slop=MATCHER_SLOP_SEC)
            self._synchronizer.registerCallback(self._on_synchronized_group)

        self._publisher = self.create_publisher(DiagnosticArray, '/multisens/sync/status', 10)
        self.create_timer(PUBLISH_PERIOD_SEC, self._publish_status)

        self.get_logger().info(
            f'synchronizing modalities {self._modalities}, tolerance={self._tolerance_ms}ms')

    @staticmethod
    def _load_modalities(config_path: str):
        if not os.path.isfile(config_path):
            return []
        with open(config_path) as f:
            data = yaml.safe_load(f) or {}
        return [entry['modality'] for entry in data.get('sensors', [])]

    def _make_watchdog_cb(self, modality: str):
        def cb(_msg):
            self._last_seen_monotonic[modality] = time.monotonic()
        return cb

    def _on_synchronized_group(self, *msgs):
        stamps_sec = {}
        for modality, msg in zip(self._modalities, msgs):
            stamps_sec[modality] = msg.header.stamp.sec + msg.header.stamp.nanosec * 1e-9

        mean_stamp = sum(stamps_sec.values()) / len(stamps_sec)
        self._last_group_offsets_ms = {
            modality: (stamp - mean_stamp) * 1000.0
            for modality, stamp in stamps_sec.items()
        }
        self._last_group_max_skew_ms = (
            (max(stamps_sec.values()) - min(stamps_sec.values())) * 1000.0)
        self._last_group_monotonic = time.monotonic()
        self._window_group_count += 1

    def _publish_status(self):
        now = time.monotonic()
        elapsed = now - self._window_start_monotonic
        group_rate_hz = self._window_group_count / elapsed if elapsed > 0 else 0.0
        self._window_group_count = 0
        self._window_start_monotonic = now

        missing = [m for m in self._modalities if m not in self._last_seen_monotonic]
        stale = [
            m for m in self._modalities
            if m in self._last_seen_monotonic
            and now - self._last_seen_monotonic[m] > STALE_AFTER_SEC
        ]
        group_is_fresh = (
            self._last_group_monotonic is not None
            and now - self._last_group_monotonic <= STALE_AFTER_SEC)

        values = [
            KeyValue(key='tolerance_ms', value=f'{self._tolerance_ms:.1f}'),
            KeyValue(key='synchronized_group_rate_hz', value=f'{group_rate_hz:.1f}'),
            KeyValue(key='missing_sensors', value=','.join(missing) if missing else 'none'),
            KeyValue(key='stale_sensors', value=','.join(stale) if stale else 'none'),
        ]

        within_tolerance = False
        if group_is_fresh:
            within_tolerance = self._last_group_max_skew_ms <= self._tolerance_ms
            values.append(KeyValue(key='max_skew_ms', value=f'{self._last_group_max_skew_ms:.1f}'))
            for modality in self._modalities:
                offset = self._last_group_offsets_ms.get(modality)
                values.append(KeyValue(
                    key=f'offset_ms_{modality}',
                    value=f'{offset:.1f}' if offset is not None else 'unavailable'))
        else:
            values.append(KeyValue(key='max_skew_ms', value='unavailable'))
            for modality in self._modalities:
                values.append(KeyValue(key=f'offset_ms_{modality}', value='unavailable'))

        if not group_is_fresh:
            level = DiagnosticStatus.ERROR
            message = f'no synchronized group in last {STALE_AFTER_SEC:.0f}s (missing: {missing or "none"})'
        elif missing:
            level = DiagnosticStatus.ERROR
            message = f'missing sensors: {missing}'
        elif stale or not within_tolerance:
            level = DiagnosticStatus.WARN
            message = f'stale: {stale or "none"}, within_tolerance={within_tolerance}'
        else:
            level = DiagnosticStatus.OK
            message = f'synchronized within {self._tolerance_ms:.0f}ms tolerance'

        status = DiagnosticStatus()
        status.name = 'multisens: sync'
        status.hardware_id = 'sync'
        status.level = level
        status.message = message
        status.values = values

        msg = DiagnosticArray()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.status = [status]
        self._publisher.publish(msg)


def main(args=None):
    rclpy.init(args=args)
    node = SyncStatusNode()
    executor = MultiThreadedExecutor(num_threads=4)
    executor.add_node(node)
    try:
        executor.spin()
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
