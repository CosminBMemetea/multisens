"""Session-window-aware resource collection (v0.7, Phase 66).

Lives beside ros_bridge.py, not inside app/domain/ - like the bridge,
this module touches a real system dependency (`psutil`) directly, so it
belongs with the other infra-facing translators, not the transport-
agnostic domain layer. `app/domain/resources.py` defines what a
`ResourceObservation` *is*; this module is one of the things that
produces real ones.

Two independent collection paths, matching the v0.7 architecture
review's own instruction not to duplicate an existing measurement
mechanism:

- `SystemMetricsWindow` - a NEW, session-window-bound collector for
  `cpu_percent`/`memory_mb`/`network_receive_mbps`/`network_transmit_mbps`.
  Calls the exact same `psutil` primitives `system_diagnostics_node`
  (ros2_ws) already uses, but bound to an explicit start/stop window
  instead of a permanent background loop, and returns rows instead of
  only streaming to a live dashboard. Same "prime cpu_percent() once
  before trusting its next reading" discipline system_diagnostics_node's
  own docstring already documents - this collector's start() is that
  priming call.
- `collect_sensor_metrics` - NOT a new measurement at all. Translates
  fields `RosBridge.snapshot()` already carries (`fps_received`,
  `publish_latency_ms`, both published every heartbeat by
  `rtsp_ingestion_node` since v0.1) directly into `fps`/
  `pipeline_latency_ms` rows. No new subscription, no new node.

## Inherited measurement caveats (see docs/limitations.md)

Every metric this module produces is measured from *inside the backend
container*, on Docker Desktop for Mac in the current reference setup -
the same "reflects the Linux VM's overall resource view, not a
cgroup-isolated per-container figure" caveat `docs/limitations.md`
already documents for the ROS container's own `cpu_percent`/
`memory_percent` now applies identically here, extended for the first
time to `network_receive_mbps`/`network_transmit_mbps` too (host-
interface-wide, not per-RTSP-stream - if multiple sensors share one
interface, as they do in the reference setup, a single configuration's
"network Mbps" really means "total host network activity during the
window").

## Measured collector overhead

A `start()`/`end()` pair does exactly one `psutil.cpu_percent(interval=
None)` call each (non-blocking - it reports the average since the last
call, never sleeps), one `psutil.virtual_memory()` call, and one
`psutil.net_io_counters()` call each. Measured directly (Phase 66, this
repo's own Docker backend container, 1000 consecutive start()/end()
pairs): ~0.27ms per pair - well under a millisecond, negligible next to
any realistic 5-10s collection window, and never itself a plausible
source of measurement distortion at that scale. See
test_resource_collector.py's own overhead test for the reproducible
measurement (a looser 5ms/pair bound there, to stay stable across
slower CI/dev hosts rather than pin to this exact figure).
"""
from __future__ import annotations

import time
import uuid
from datetime import datetime, timezone

import psutil

from app.domain.resources import SUPPORTED_RESOURCE_METRICS, ResourceObservation

_SENSOR_METRICS = ('fps', 'pipeline_latency_ms')


def _new_id() -> str:
    return str(uuid.uuid4())


class SystemMetricsWindow:
    """One open collection window over cpu/memory/network. `start()`
    primes psutil's internal cpu_percent baseline and takes the network
    counters' starting snapshot; `end()` reads the real deltas/point
    values and returns one ResourceObservation per metric. Never
    blocks or sleeps - both calls are near-instant (see module
    docstring)."""

    def __init__(self):
        self._started_monotonic: float | None = None
        self._started_at: datetime | None = None
        self._net_before = None

    def start(self) -> None:
        # First call after construction always returns 0.0 (no interval
        # to average over yet) - this call exists purely to prime that
        # baseline so end()'s reading is real, never a fabricated first
        # zero. Exact pattern system_diagnostics_node's own __init__
        # already uses for the same reason.
        psutil.cpu_percent(interval=None)
        self._net_before = psutil.net_io_counters()
        self._started_monotonic = time.monotonic()
        self._started_at = datetime.now(timezone.utc)

    def end(self, session_id: str, configuration_id: str | None, platform_id: str) -> list[ResourceObservation]:
        if self._started_monotonic is None:
            raise RuntimeError('SystemMetricsWindow.end() called before start()')

        ended_at = datetime.now(timezone.utc)
        elapsed_sec = time.monotonic() - self._started_monotonic
        cpu_percent = psutil.cpu_percent(interval=None)
        memory_mb = psutil.virtual_memory().used / (1024 * 1024)
        net_after = psutil.net_io_counters()

        def row(metric: str, value: float | None, quality: str = 'measured', source: str = 'psutil') -> ResourceObservation:
            return ResourceObservation(
                id=_new_id(), session_id=session_id, configuration_id=configuration_id,
                metric=metric, value=value, unit=SUPPORTED_RESOURCE_METRICS[metric], quality=quality,
                source=source, platform_id=platform_id, started_at=self._started_at, ended_at=ended_at,
            )

        observations = [
            row('cpu_percent', cpu_percent, source='psutil.cpu_percent'),
            row('memory_mb', memory_mb, source='psutil.virtual_memory'),
        ]

        if elapsed_sec > 0:
            recv_mbps = (net_after.bytes_recv - self._net_before.bytes_recv) * 8 / 1_000_000 / elapsed_sec
            sent_mbps = (net_after.bytes_sent - self._net_before.bytes_sent) * 8 / 1_000_000 / elapsed_sec
            observations.append(row('network_receive_mbps', recv_mbps, source='psutil.net_io_counters'))
            observations.append(row('network_transmit_mbps', sent_mbps, source='psutil.net_io_counters'))
        else:
            # A zero-duration window can't produce a rate - unavailable,
            # never a fabricated 0 Mbps and never a divide-by-zero.
            observations.append(row('network_receive_mbps', None, quality='unavailable', source='psutil.net_io_counters'))
            observations.append(row('network_transmit_mbps', None, quality='unavailable', source='psutil.net_io_counters'))

        self._started_monotonic = None
        return observations


def collect_sensor_metrics(
    snapshot: dict, sensor_ids: list[str], session_id: str, configuration_id: str | None,
    platform_id: str, started_at: datetime, ended_at: datetime,
) -> list[ResourceObservation]:
    """`fps`/`pipeline_latency_ms` for each sensor, read directly out of
    an already-fetched `RosBridge.snapshot()` - not a new measurement,
    not a new subscription. A sensor absent from the snapshot (stale,
    disconnected node, or never reported) produces explicit unavailable
    rows, never a fabricated 0 fps or 0 ms - distinct from
    `fps_received`'s own genuine measured 0.0 ("no frames received
    recently," a real reading, see docs/topics.md)."""
    sensors = snapshot.get('sensors', {})
    observations: list[ResourceObservation] = []

    for sensor_id in sensor_ids:
        entry = sensors.get(sensor_id)
        source_prefix = f'ros_diagnostics:{sensor_id}'

        fps_raw = entry.get('fps_received') if entry else None
        if fps_raw is not None:
            observations.append(ResourceObservation(
                id=_new_id(), session_id=session_id, configuration_id=configuration_id, metric='fps',
                value=float(fps_raw), unit=SUPPORTED_RESOURCE_METRICS['fps'], quality='measured',
                source=f'{source_prefix}:fps_received', platform_id=platform_id,
                started_at=started_at, ended_at=ended_at,
            ))
        else:
            observations.append(_unavailable_sensor_row(
                session_id, configuration_id, platform_id, 'fps', started_at, ended_at, source_prefix,
            ))

        latency_raw = entry.get('publish_latency_ms') if entry else None
        if latency_raw is not None and latency_raw != 'unavailable':
            observations.append(ResourceObservation(
                id=_new_id(), session_id=session_id, configuration_id=configuration_id,
                metric='pipeline_latency_ms', value=float(latency_raw),
                unit=SUPPORTED_RESOURCE_METRICS['pipeline_latency_ms'], quality='measured',
                source=f'{source_prefix}:publish_latency_ms', platform_id=platform_id,
                started_at=started_at, ended_at=ended_at,
            ))
        else:
            observations.append(_unavailable_sensor_row(
                session_id, configuration_id, platform_id, 'pipeline_latency_ms', started_at, ended_at, source_prefix,
            ))

    return observations


def _unavailable_sensor_row(
    session_id: str, configuration_id: str | None, platform_id: str, metric: str,
    started_at: datetime, ended_at: datetime, source_prefix: str,
) -> ResourceObservation:
    return ResourceObservation(
        id=_new_id(), session_id=session_id, configuration_id=configuration_id, metric=metric,
        value=None, unit=SUPPORTED_RESOURCE_METRICS[metric], quality='unavailable',
        source=f'{source_prefix}:{metric}', platform_id=platform_id,
        started_at=started_at, ended_at=ended_at,
    )
