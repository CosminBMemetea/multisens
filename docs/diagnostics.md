# Diagnostics & Health Model

How to read MultiSens's health signals, and why they're structured the way
they are. For the exact wire-level fields, see [topics.md](topics.md); this
document is the "what does this mean and why should I trust it" companion.

## Three independent layers, each aging out its own stale data

A recurring, hard-won lesson from this project (Phase 8, restated because
it matters): **a health/staleness mechanism built in one place does not
automatically protect any other place that stores the same kind of "is this
still current" data.** MultiSens has three separate layers that each
independently track "have I heard from X recently," because each one sits
at a different point where staleness can be introduced:

1. **Per-sensor self-reporting** (`rtsp_ingestion_node`): knows its own
   `connection_state` directly - it owns the RTSP connection, so it's the
   only thing that can honestly say "connected" vs "disconnected." No
   staleness math needed here; it's a live self-report.
2. **Global aggregation** (`system_diagnostics_node`): ages out a sensor
   from `connected_sensor_count` if it hasn't reported `OK` in the last 3s
   - protects against a sensor's *reporting node* going silent (crashed,
   killed), not just its RTSP connection dropping.
3. **Backend translation** (`ros_bridge.py`): ages out a sensor from
   `/api/status` / the dashboard if its diagnostics haven't updated in the
   last 5s. Added in Phase 8 after finding, by testing it directly, that
   without this layer a sensor whose reporting node died would show
   `"connected"` with a frozen-fresh `fps_received` **forever** in the
   dashboard - the earlier two layers were correct, but this third hop
   (ROS → backend → browser) hadn't been given the same treatment.

If you're extending this system and adding a fourth place that stores "is
this sensor's data current" - a cache, another bridge, a second dashboard -
give it its own staleness check. Don't assume it inherits one from upstream.

## Reading the levels

`DiagnosticStatus.level`, surfaced in the dashboard as OK (green) / WARN
(amber) / ERROR (red):

- **Per-sensor**: `OK` if connected, `ERROR` if disconnected. No `WARN`
  state for sensors - a stream is either delivering frames or it isn't.
- **System**: `OK` only if every configured sensor is currently connected;
  `WARN` otherwise (not `ERROR` - the system itself is still functioning,
  just short a sensor).
- **Sync**: `OK` if all sensors are synchronized within `tolerance_ms`;
  `WARN` if skew exceeds tolerance or a sensor is stale-but-still-seen;
  `ERROR` if a sensor is missing entirely or no synchronized group has
  formed recently at all.

## What's real vs. explicitly unavailable

Every numeric diagnostic field is either a genuine measurement or the
literal string `"unavailable"` - never a fabricated placeholder (`0`,
`null`, a guessed default). The two fields that are *always*
`"unavailable"` by design, not a bug:

- **`frames_dropped`**: OpenCV's FFmpeg backend doesn't expose RTP-level
  packet loss statistics through a usable API. Reporting `0` here would
  claim a verification that was never actually performed.
- **`sync`'s offset/skew fields, when no group has matched recently**:
  showing the *last* known-good numbers past their staleness window would
  misrepresent them as current.

If you see `"unavailable"` somewhere, that's the system being honest about
a real measurement gap - not a placeholder waiting to be filled in.

## `publish_latency_ms` is not end-to-end latency

It measures the time from `cv2.VideoCapture.read()` returning to
`publish()` returning, inside `rtsp_ingestion_node` - typically 1-7ms in
practice. It says nothing about capture-to-display latency, network
latency, or anything upstream of the RTSP read. There is no field for true
end-to-end latency in v0.1, because RTSP doesn't provide a reliable source
capture timestamp to measure from (see
[topics.md](topics.md#multisenssensorsmodalityimage_raw)).

## `reconnect_count` does not span process respawns

It counts RTSP-level reconnects handled by a node's own retry loop, reset
to `0` whenever that node's *process* restarts (crash + `respawn`, or a
container restart) - a genuinely new process has had no reconnects yet in
its own lifetime. Confirmed directly in Phase 9: killing a sensor's process
and observing the recovered process correctly report `reconnect_count: 0`.
If you need a sensor's full reliability history across process restarts,
this field alone won't give it to you - check container/node logs.

## Troubleshooting quick reference

| Symptom | Likely meaning |
|---|---|
| One sensor `DISCONNECTED`, others fine | That sensor's RTSP source is down or unreachable; the node is retrying every 2s |
| A sensor disappears from `/api/status`/dashboard entirely | Its reporting node's *process* died and hasn't been heard from in 5s+ (see layer 3 above) - check `docker exec <ros> ps aux | grep <id>_ingestion`; `respawn` should bring it back within ~2-3s |
| `SYSTEM HEALTH: WARN` right after `docker compose up` | Likely a real, brief, honest DDS-discovery startup race - the backend genuinely hasn't heard from every sensor yet. Should self-correct within a few seconds; if it doesn't, something is actually wrong |
| `SYNC HEALTH: WARN` with skew just over `tolerance_ms` | Transient jitter, common right after a restart or under host CPU load - watch whether it settles; a *sustained* high skew is a real problem |
| `frames_dropped: unavailable` | Expected, always - not a bug (see above) |
