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
| 2 — RGB RTSP → ROS image topic | One real sensor, real frames | 🚧 In progress |
| 3 — Generalize ingestion (RGB+depth+thermal from config) | — | ⬜ Not started |
| 4 — Diagnostics | — | ⬜ Not started |
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
  is down.
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

## Running Phase 1 (current)

```bash
docker compose build ros
docker compose up -d ros
docker compose logs -f ros      # watch the placeholder graph exchange messages
docker compose ps               # should show "healthy"
docker compose down
```

`ros2_ws/src/multisens_ingestion` currently contains a placeholder
talker/listener pair, not real sensor ingestion yet — Phase 1's job was
proving the container, launch mechanism, and DDS discovery work reliably on
Docker Desktop for Mac before anything real is built on top of it. Real RTSP
ingestion lands in Phase 2.

## Requirements

- Docker Desktop (tested with 6GB RAM / 7 CPU allocated to the VM)
- For local sensor simulation: [`rtspmultistream`](https://github.com/CosminBMemetea/multirtsp)
  (separate repo — the RTSP endpoints are the integration boundary; this repo
  has no dependency on how they're produced)

## License

Apache-2.0 — see [LICENSE](LICENSE).
