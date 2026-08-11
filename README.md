# MultiSens

Open-source, vendor-neutral platform for ingesting, synchronizing, and
visualizing heterogeneous sensor streams (RGB, depth, thermal, and beyond),
with an eye toward later perception evaluation, sensor ablation, and
ground-truth comparison. Built to work identically whether a stream comes
from a webcam-based simulator, a real sensor, or an OEM gateway — no
vendor-specific or dataset-specific code lives in this repo.

## Status: what's actually running vs. what's designed but not built

| Phase | What it delivers | Status |
|---|---|---|
| 0 — Environment & architecture | Container topology, ROS message strategy, video/control-plane split reviewed and decided | ✅ Done |
| 1 — ROS graph boots in Docker | `ros` container builds on `ros:humble-ros-base` (arm64), boots a two-node graph, cross-process DDS pub/sub verified live (not just node discovery — actual message delivery watched via `ros2 topic echo`) | ✅ Done |
| 2 — RGB RTSP → ROS image topic | One real sensor, real frames | ✅ Done |
| 3 — Generalize ingestion (RGB+depth+thermal from config) | One node type, N instances from `config/sensors.yaml`, no per-sensor code | ✅ Done |
| 4 — Diagnostics | Per-sensor self-reported diagnostics + global system diagnostics, both real | ✅ Done |
| 5 — Synchronization | — | ⬜ Not started |
| 6 — Backend API/bridge | — | ⬜ Not started |
| 7 — Web dashboard | — | ⬜ Not started |
| 8 — Robustness (disconnect/reconnect) | — | ⬜ Not started |
| 9 — Docs & v0.1 release | — | ⬜ Not started |

Tracked as GitHub issues, one per phase — see [Issues](https://github.com/CosminBMemetea/multisens/issues)
for what's open vs. closed right now; this table is a snapshot, the issue
tracker is the live source of truth.

No CI is configured yet. Nothing here has been claimed as verified without
actually running it — see each phase's closing issue comment for exactly
what was checked and how.

## Architecture, in brief

- **ROS 2 Humble** is the internal metadata/synchronization/diagnostics layer.
  It never carries pixels to the browser — DDS-transporting raw video across
  containers at 30fps would be real CPU load on the 8GB-class machines this
  targets. ROS's job is timing, identity, and health, not video delivery.
- **RTSP is the integration boundary.** One generic, configuration-driven
  ingestion component — never three hardcoded sensor implementations. Adding
  a fourth sensor is a `config/sensors.yaml` entry, not a code change.
- **Video reaches the browser independently of ROS**: the backend opens its
  own RTSP connection (same config, same URLs) and relays MJPEG over HTTP —
  simple, no signaling/ICE complexity, and the video path works even if ROS
  is down. Measured evidence this is the right call, not just a guess: a
  generic `rclpy` subscriber to a single 640x480 `bgr8` image topic
  (~900KB/frame) could not keep up with the true 30fps publish rate in this
  setup — publish-side stayed a steady 30fps throughout, the drop was on a
  second, independent subscriber trying to consume the same raw stream.
- **No custom ROS messages.** `sensor_msgs/Image`, `sensor_msgs/CameraInfo`,
  and `diagnostic_msgs/DiagnosticArray` cover everything needed for v0.1;
  `DiagnosticArray`'s `KeyValue` list carries modality/source_type/fps/offset
  fields that don't have a dedicated standard message field.
- **PHYSICAL vs. SIMULATED is a hard distinction, always labeled.** The
  reference sensor simulator ([`rtspmultistream`](https://github.com/CosminBMemetea/multirtsp))
  produces one real RGB feed from a webcam and two synthetic depth/thermal
  visualizations derived from it via FFmpeg's `pseudocolor` filter — those are
  never presented as physical depth or temperature measurements, in the ROS
  graph, diagnostics, or UI.

Full phase-by-phase development log lives in the issue tracker; each closed
issue documents what was actually verified for that phase, not just what was
attempted.

## Running Phase 4 (current)

Start the sensor simulator on the host first (separate repo:
[`multirtsp`](https://github.com/CosminBMemetea/multirtsp)):

```bash
mediamtx ./mediamtx.yml     # from the multirtsp checkout
./stream_macos.sh           # from the multirtsp checkout
```

Then:

```bash
docker compose build ros
docker compose up -d ros
docker compose logs -f ros      # watch rgb/depth/thermal all publish at ~30fps
docker compose ps               # should show "healthy"
docker compose down
```

`ingestion.launch.py` reads `config/sensors.yaml` (mounted read-only into the
container) and instantiates one `rtsp_ingestion_node` per entry — the node
itself didn't need to change from Phase 2, since sensor identity was already
fully parameterized. Verified end to end, not just "three topics exist":
pulled a real frame from each of `/multisens/sensors/{rgb,depth,thermal}/image_raw`
and scored colorfulness (mean `|R-G|+|G-B|+|R-B|` per pixel) — rgb scored 36
(a face against a mostly neutral wall), depth scored 372 and thermal scored
334 (the `pseudocolor` `turbo`/`heat` presets are visibly, measurably applied,
not passthrough grayscale). `source_type` was read back via `ros2 param get`
for all three nodes and matches config exactly (`physical` for rgb,
`simulated` for depth/thermal). The launch file also validates the config
before launching anything: two sensors declaring the same modality (which
would silently collide on the same topic) is a hard launch-time error, tested
directly by feeding it a broken config.

Depth/thermal reconnect behavior (killing the simulator) was covered
end-to-end for rgb in Phase 2's node — same code path, not re-verified per
modality here since it's the same node type.

The Phase 1/2 launch files (`phase1_graph.launch.py`, `phase2_rgb.launch.py`)
are still in the package, unused by the container's default entrypoint —
harmless historical artifacts, not dead weight worth deleting yet.

### Diagnostics (Phase 4)

Every `rtsp_ingestion_node` self-publishes its own status on
`/multisens/diagnostics` (`diagnostic_msgs/DiagnosticArray`, one
`DiagnosticStatus` per publish) every second: `connection_state`,
`fps_received`, `fps_expected` (from the new optional `expected_fps` field in
`config/sensors.yaml`), `resolution`, `encoding`, `frames_received`,
`last_frame_age_ms`, `reconnect_count`, `publish_latency_ms`, `source_type`,
`modality`. `frames_dropped` is always reported as `"unavailable"` rather than
a fabricated `0` — OpenCV's FFmpeg backend doesn't expose RTP-level loss
stats through a simple API, and claiming zero drops would be a metric this
system hasn't actually measured.

Per-sensor diagnostics are self-reported rather than computed by a separate
node watching the image topics, on purpose: only the ingestion node itself
genuinely knows `connection_state`, `reconnect_count`, and true
resolution/encoding — a passive external subscriber could only guess at
those from message arrival gaps, which the "don't fabricate metrics" rule
in this project rules out.

A separate `multisens_diagnostics` package/node publishes *global*
diagnostics on the same topic every 2s — `cpu_percent`, `memory_percent`,
`uptime_sec`, `connected_sensor_count`, `total_sensor_count`, and
`sync_health` (`"unavailable"`, honestly — Phase 5 doesn't exist yet, so
there is nothing to measure). This is separate because no single sensor owns
host resource usage or "how many sensors are connected total." Note:
`cpu_percent`/`memory_percent` are read via `psutil` from inside the
container on Docker Desktop for Mac, which reflects the Linux VM's overall
view, not a cgroup-isolated per-container figure — a real, honestly-labeled
measurement, just not perfectly scoped; worth revisiting if this ever runs
under a container runtime with proper cgroup accounting.

Verified end to end, including a bug this caught: the system node's first
version subscribed to the same `/multisens/diagnostics` topic it publishes
to, so it received its own "system" status back and miscounted it as a 4th
connected sensor (`connected_sensor_count: 4` with `total_sensor_count: 3`
— caught by actually reading the field values, not just checking the topic
existed). Fixed by only counting hardware_ids that are actual configured
sensors. After the fix: killed the RTSP source, confirmed all three sensors
flip to `connection_state: disconnected` / diagnostic level `ERROR`,
`fps_received: 0.0`, and `last_frame_age_ms` growing correctly, while
`system` correctly reports `0/3 configured sensors connected`. Restarted the
source and confirmed full recovery with `reconnect_count` incrementing to
`1` on all three nodes and `system` back to `3/3`.

## Requirements

- Docker Desktop (tested with 6GB RAM / 7 CPU allocated to the VM)
- For local sensor simulation: [`rtspmultistream`](https://github.com/CosminBMemetea/multirtsp)
  (separate repo — the RTSP endpoints are the integration boundary; this repo
  has no dependency on how they're produced)

## License

Apache-2.0 — see [LICENSE](LICENSE).
