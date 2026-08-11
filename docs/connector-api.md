# Adding a Sensor to MultiSens (v0.1)

MultiSens does not have a plugin API in v0.1 - "connecting a sensor" means
adding one entry to [`config/sensors.yaml`](../config/sensors.yaml). No code
changes, no rebuild of any container. This is the actual, working answer to
"how do I add a fourth sensor," verified directly in Phase 3 and again
implicitly in every phase since (the reference config already has three
independently-configured entries, not one hardcoded per sensor).

## Requirements on the sensor side

MultiSens's only integration boundary in v0.1 is **RTSP**. Your sensor (or
whatever bridges it to RTSP - a real camera driver, an OEM gateway, a
recorded-dataset player) needs to:

- Serve H.264 video over RTSP, reachable from inside the `ros` and
  `backend` containers.
- Accept a TCP RTSP transport (`rtsp_ingestion_node` and the backend's video
  relay both connect with `-rtsp_transport tcp` / `cv2.CAP_FFMPEG` over
  TCP).
- Be reachable at a stable URL. The reference config uses
  `host.docker.internal`, which is a Docker-Desktop-for-Mac-specific
  convenience (confirmed to reach even a loopback-bound host service) - see
  [architecture.md](architecture.md#portability) for what changes on other
  platforms.

MultiSens does not care *how* the RTSP stream is produced - a real depth
camera's own RTSP output works identically to the reference webcam
simulator's synthetic depth visualization, from MultiSens's point of view.
The only thing that must stay honest is the `source_type` field described
below.

## `config/sensors.yaml` schema

```yaml
sensors:
  - id: <string, required>          # unique, becomes the ROS node name
                                     # "<id>_ingestion"
    modality: <string, required>    # becomes the topic namespace:
                                     # /multisens/sensors/<modality>/*
    source_type: <physical|simulated, required>
    transport: <string, required>   # only "rtsp" is implemented; other
                                     # values are skipped with a logged
                                     # warning, not a crash
    url: <string, required>         # RTSP URL
    expected_fps: <number, optional># nominal capture rate, purely for
                                     # diagnostics comparison - omit if
                                     # genuinely unknown rather than
                                     # guessing a number
```

**`id`**: must be unique across the file. Used as the ROS node name
(`{id}_ingestion`) and as the `hardware_id` in diagnostics.

**`modality`**: must also be unique across the file - **this is enforced**,
not just documented. Two entries sharing a modality would collide on the
same `/multisens/sensors/{modality}/image_raw` topic; `ingestion.launch.py`
raises a hard error at launch time rather than allowing that, verified in
Phase 3 by feeding it a deliberately broken config. This is the concrete
limit described in [architecture.md](architecture.md#known-limitations-v01-deliberate):
one sensor per modality in v0.1.

**`source_type`**: `physical` means the stream is genuine sensor data.
`simulated` means it's synthetic (like the reference depth/thermal
visualizations, which are FFmpeg `pseudocolor` transforms of the RGB feed,
not physical depth or temperature measurements). This value is surfaced
directly in diagnostics and the dashboard's PHYSICAL/SIMULATED badge -
**never set this to `physical` for a synthetic source.** The whole point of
this field, stated from the project's original design brief, is that a
consumer must never be misled into thinking synthetic data is real
measurement.

**`transport`**: only `"rtsp"` does anything in v0.1. Present in the schema
now (rather than assumed) so that adding a second transport later - if a
sensor ever needs one - is a natural extension of an existing field rather
than a breaking schema change.

**`expected_fps`**: optional. If omitted, diagnostics report `fps_expected:
"unavailable"` rather than a fabricated default - see
[topics.md](topics.md) for the full diagnostics field reference.

## What happens automatically once a sensor is in config

1. `ingestion.launch.py` instantiates one `rtsp_ingestion_node` for it,
   parameterized entirely from the config entry.
2. Its topics (`image_raw`, `frame_stamp`) and per-sensor diagnostics exist
   immediately.
3. `system_diagnostics_node` includes it in `total_sensor_count` and
   `connected_sensor_count` automatically (it reads the same config file).
4. `sync_status_node` includes it in the timestamp-synchronized group
   automatically (same config file again).
5. `backend`'s `/api/sensors` and `/api/sensors/{id}/stream.mjpeg` pick it
   up automatically (same config file, read independently by the backend -
   see [`backend/app/config.py`](../backend/app/config.py)).
6. The dashboard's sensor grid renders a card for it automatically - the
   frontend has no hardcoded sensor list, it maps over whatever
   `GET /api/sensors` returns.

No component in this codebase has "rgb", "depth", or "thermal" hardcoded as
a sensor identity - those three strings only appear in the reference
[`config/sensors.yaml`](../config/sensors.yaml) itself.

## Backend API surface (for building an alternative frontend, or scripting)

See [architecture.md](architecture.md#the-two-planes-controltelemetry-vs-video)
for the design rationale (video and control/telemetry are deliberately
separate transports).

- `GET /api/health` - liveness check, `{"status": "ok"}`.
- `GET /api/sensors` - the parsed `config/sensors.yaml` `sensors` list, as
  JSON.
- `GET /api/status` - current translated diagnostics/sync snapshot (see
  [topics.md](topics.md) for field meanings - same KeyValue fields, just
  flattened to plain JSON by `ros_bridge.py` rather than ROS message
  types). Entries older than 5s are excluded, not returned stale - a sensor
  whose reporting node has died disappears from this response rather than
  showing frozen last-known values.
- `GET /api/sensors/{id}/stream.mjpeg` - `multipart/x-mixed-replace`
  MJPEG video for one sensor id from `config/sensors.yaml`. 404 for an
  unknown id.
- `WS /ws/status` - pushes the same object as `GET /api/status` every
  500ms.

All REST responses are plain JSON with no ROS-specific framing - this
backend is the translation boundary described in
[architecture.md](architecture.md#the-two-planes-controltelemetry-vs-video);
nothing downstream of it needs to know ROS exists.
