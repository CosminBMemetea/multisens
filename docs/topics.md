# MultiSens ROS Topic Contract (v0.1)

All topics use only standard ROS message types - no custom `.msg` files
exist in this repo (see [architecture.md](architecture.md#no-custom-ros-messages)
for why). `{sensor_id}` is whatever string a sensor's config entry
declares as its `id` (`rgb`, `depth`, `thermal` in the reference config -
not hardcoded; two sensors may share one `modality` and still get their
own independent topics, e.g. `ridesafe_front_rgb`/`ridesafe_rear_rgb`,
both `modality: rgb` - see "Resolved, v1.0-RC" in
[architecture.md](architecture.md#known-limitations-v01-deliberate)).
`modality` itself is metadata, carried in diagnostics only, never part
of a topic path (since v1.0-RC issue #121 - topics were modality-keyed
before that).

## Per-sensor topics

Published by each `rtsp_ingestion_node` instance
([source](../ros2_ws/src/multisens_ingestion/multisens_ingestion/rtsp_ingestion_node.py)).

### `/multisens/sensors/{sensor_id}/image_raw`

- **Type**: `sensor_msgs/Image`
- **QoS**: `qos_profile_sensor_data` (best-effort, small depth) - a slow
  subscriber drops old frames rather than backing up an unbounded queue.
- **Encoding**: always `bgr8` (converted from the decoded RTSP frame via
  `cv_bridge`).
- **`header.stamp`**: the ROS clock time at the moment this node published
  the message - **not** a source capture timestamp. RTSP/H.264 does not
  reliably provide one across independently-read streams; this field should
  never be interpreted as "when the sensor captured this frame," only "when
  this node published it."
- **`header.frame_id`**: `multisens_{sensor_id}`.

### `/multisens/sensors/{sensor_id}/frame_stamp`

- **Type**: `sensor_msgs/TimeReference`
- **QoS**: `qos_profile_sensor_data`, same as `image_raw`.
- **Purpose**: a lightweight (few hundred bytes, vs. ~900KB for `image_raw`)
  companion carrying the *same* header as the paired `image_raw` message,
  for consumers that need frame timing at full rate without paying the cost
  of the pixel payload. Added in Phase 5 specifically for
  `multisens_sync` - see [architecture.md](architecture.md#the-two-planes-controltelemetry-vs-video)
  for why a generic subscriber can't sustain `image_raw` at full rate.
- **`time_ref`**: set equal to `header.stamp` (redundant by design - some
  consumers read one field, some the other).
- **`source`**: the sensor's configured `id`.

### `/multisens/sensors/{sensor_id}/info`

- **Type**: `sensor_msgs/CameraInfo`
- **Status**: declared in the architecture, **not yet published in v0.1**.
  No calibration data exists for the simulated depth/thermal sources, and
  none is fabricated - when this is implemented, expect zeroed/empty fields
  for `source_type: simulated` sensors, populated fields only for sensors
  with genuine calibration data.

## Diagnostics

### `/multisens/diagnostics`

- **Type**: `diagnostic_msgs/DiagnosticArray`
- **QoS**: default (reliable, small depth) - low volume, no throughput
  concern like `image_raw`.
- **Publishers**: every `rtsp_ingestion_node` (one `DiagnosticStatus` per
  publish, `hardware_id` = sensor id, every 1s) **and**
  `system_diagnostics_node` (`hardware_id: "system"`, every 2s). Multiple
  independent publishers on one topic is the standard ROS diagnostics
  idiom - each message is one status snapshot, not a merged/aggregated
  array; a subscriber (like `backend`'s `ros_bridge.py`) accumulates the
  latest per-`hardware_id` state itself.

**Per-sensor `DiagnosticStatus.values` (KeyValue keys):**

| Key | Meaning | Can be `"unavailable"`? |
|---|---|---|
| `modality` | sensor's configured modality | no |
| `source_type` | `physical` or `simulated` | no |
| `connection_state` | `connected` / `disconnected` | no |
| `fps_received` | measured publish rate over the last ~1s window | no (0.0 if disconnected) |
| `fps_expected` | from config's optional `expected_fps` | yes, if not configured |
| `resolution` | `WIDTHxHEIGHT` of the last successfully read frame | yes, before first frame |
| `encoding` | always `bgr8` once any frame has been read | yes, before first frame |
| `frames_received` | cumulative count since node start | no |
| `frames_dropped` | **always** `"unavailable"` | always - OpenCV's FFmpeg backend doesn't expose RTP-level loss stats |
| `last_frame_age_ms` | time since the last successful frame | yes, before first frame |
| `reconnect_count` | successful RTSP re-opens after a prior connection failure, **within this node process's current lifetime** (not counting the first open) - see note below | no |
| `publish_latency_ms` | time from `cv2.VideoCapture.read()` returning to `publish()` returning - **not** end-to-end/source latency | yes, before first frame |

**`reconnect_count` does not span process respawns.** It counts RTSP-level
reconnects handled by `rtsp_ingestion_node`'s own retry loop while the
process is running. If the node's OS *process* dies and comes back via
`respawn` (see [architecture.md](architecture.md#fault-isolation-and-respawn)),
that's a new process with its own fresh counter starting at 0 - confirmed
directly in Phase 9: killing a sensor's process and observing the recovered
process report `reconnect_count: 0`, correctly, because it genuinely hasn't
had any RTSP reconnects yet in its new lifetime. Found in the same check:
`respawn` (~2-3s) now completes faster than the backend's 5s staleness
threshold, so a process-level crash-and-recover cycle is invisible in the
live dashboard - a good outcome (fast, correct recovery), just worth
knowing precisely rather than assuming this field alone tells a sensor's
whole reliability history.

**System `DiagnosticStatus.values`:**

| Key | Meaning |
|---|---|
| `cpu_percent` | via `psutil`, measured from inside the `ros` container - on Docker Desktop for Mac this reflects the Linux VM's overall view, not a cgroup-isolated per-container figure |
| `memory_percent` | same caveat as above |
| `uptime_sec` | `system_diagnostics_node`'s own process uptime |
| `connected_sensor_count` | sensors that reported `level: OK` within the last 3s (staleness-windowed, not a raw snapshot) |
| `total_sensor_count` | count of entries in `config/sensors.yaml` |
| `sync_health` | mirrors the `level` most recently seen on `/multisens/sync/status` |

`DiagnosticStatus.level`: `OK` if connected/healthy, `ERROR` if
disconnected or (for `system`) any configured sensor is missing entirely,
`WARN` for degraded-but-not-down states.

## Synchronization

### `/multisens/sync/status`

- **Type**: `diagnostic_msgs/DiagnosticArray`
- **Publisher**: `sync_status_node`, one `DiagnosticStatus`
  (`hardware_id: "sync"`) per publish, every 1s.
- **Mechanism**: `message_filters.ApproximateTimeSynchronizer` over every
  configured sensor's `frame_stamp` topic - see
  [architecture.md](architecture.md#synchronization-measured-not-guessed).

| Key | Meaning |
|---|---|
| `tolerance_ms` | configured skew tolerance (`ros2 param`, default 25.0 - see architecture.md for how this default was set) |
| `synchronized_group_rate_hz` | how often a full N-way timestamp-matched group was found in the last publish window |
| `missing_sensors` | comma-separated sensor ids never seen at all, or `"none"` |
| `stale_sensors` | comma-separated sensor ids seen before but not within the last 3s, or `"none"` |
| `max_skew_ms` | max timestamp spread within the most recent matched group; `"unavailable"` if no group matched within the last 3s |
| `offset_ms_{sensor_id}` | that sensor's offset from the matched group's mean timestamp; `"unavailable"` under the same condition as `max_skew_ms` |

### `/multisens/sync/frames`

**Not implemented in v0.1**, by design - see
[architecture.md](architecture.md#known-limitations-v01-deliberate). Would
carry actual grouped/republished synchronized frame bundles, as opposed to
status *about* synchronization.

## Node parameters (not topics, but part of the contract)

Static per-sensor identity that doesn't change at runtime is exposed as ROS
parameters on each `rtsp_ingestion_node`, inspectable via `ros2 param get
/{id}_ingestion {param}`: `sensor_id`, `modality`, `source_type`,
`rtsp_url`, `expected_fps`. `sync_status_node` exposes `tolerance_ms`.
