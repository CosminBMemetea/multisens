# Configuration Reference

Every configuration surface in MultiSens, in one place. See
[architecture.md](architecture.md) for why things are structured this way,
[connector-api.md](connector-api.md) for the sensor-onboarding workflow this
config drives.

## `config/sensors.yaml`

The single source of truth for "what sensors exist." Read independently by
`ingestion.launch.py`, `system_diagnostics_node`, `sync_status_node`, and
the `backend` container - every one of them reads the *same file* (see
[Environment variables](#environment-variables) below), so there is no
separate sensor list to keep in sync.

```yaml
sensors:
  - id: <string, required>          # unique; becomes the ROS node name
                                     # "<id>_ingestion" and the diagnostics
                                     # hardware_id
    modality: <string, required>    # unique across the file (enforced -
                                     # duplicate modalities are a hard
                                     # launch-time error); becomes the topic
                                     # namespace /multisens/sensors/<modality>/*
    source_type: <physical|simulated, required>
    transport: <string, required>   # only "rtsp" does anything in v0.1;
                                     # other values are skipped with a
                                     # logged warning, not a crash
    url: <string, required>         # RTSP URL, TCP transport
    expected_fps: <number, optional># nominal capture rate, diagnostics-only;
                                     # omit if genuinely unknown
```

Full field-by-field rationale, including why `source_type` must never be
faked, is in [connector-api.md](connector-api.md#configsensorsyaml-schema).

**Mounted, not baked in.** `docker-compose.yml` mounts this file read-only
into both `ros` and `backend` (`./config/sensors.yaml:/config/sensors.yaml:ro`).
Editing it and restarting the affected container(s) is enough - no image
rebuild required.

## Environment variables

| Variable | Set in | Read by | Purpose |
|---|---|---|---|
| `ROS_DOMAIN_ID` | `.env` (repo root) | `ros`, `backend` (via `docker-compose.yml` `${...}` substitution) | DDS domain - `ros` and `backend` must agree on this to discover each other's graph at all. Single-sourced in `.env` since Phase 6 (previously duplicated in two places, a real bug risk). |
| `RMW_IMPLEMENTATION` | `.env` (repo root) | `ros`, `backend` | Pinned to `rmw_cyclonedds_cpp` for both - Docker Desktop for Mac's default DDS discovery (multicast) is known to be flaky in this networking setup; CycloneDDS with explicit domain/RMW agreement was verified (Phase 1) to work reliably where the default configuration was a real risk. |
| `MULTISENS_SENSORS_CONFIG` | `docker-compose.yml`, per-service | `ingestion.launch.py`, `system_diagnostics_node`, `sync_status_node`, `backend/app/config.py` | Path to `sensors.yaml` inside the container. Defaults to `/config/sensors.yaml` in every reader if unset - the env var only needs to be set at all if you change the mount target. |
| `VITE_API_BASE_URL` | not set by default | `frontend/src/api.ts` | Overrides the backend URL the *browser* uses (default `http://localhost:8000`). Only needed if the backend's published port changes, or the dashboard is served from somewhere other than this repo's default `docker-compose.yml` setup. Build-time (Vite), not runtime - must be set before `docker compose build frontend`. |
| `MULTISENS_DB_PATH` | `docker-compose.yml`, `backend` only | `backend/app/persistence/db.py` | Path to the evaluation SQLite file (v0.2+: sessions/scenarios/ground truth/predictions/evaluation results). Defaults to `/data/multisens.db` if unset. Points at the `backend-data` named volume in `docker-compose.yml` - see [Docker volumes](#docker-volumes) below. |

`.env` (repo root, committed - contains no secrets, just shared non-sensitive
config) is the single source for the first two. See
[architecture.md](architecture.md) for why this file exists at all (it
replaced a real duplication bug).

## `docker-compose.yml` ports

| Service | Host port | Container port | Purpose |
|---|---|---|---|
| `backend` | `8000` | `8000` | REST + WebSocket + MJPEG, all on one port |
| `frontend` | `8080` | `80` (nginx) | Dashboard. `8080`, not `3000`, because port `3000` was occupied by an unrelated process on the machine this was developed on - change freely in `docker-compose.yml` if it collides with something on yours |
| `ros` | none published | - | Nothing outside the Docker network needs to reach it directly; `backend` reaches it over the compose network via DDS |

## Docker volumes

| Volume | Mount | Purpose |
|---|---|---|
| `backend-data` (named) | `/data` in `backend` | The evaluation SQLite database (v0.2+) - survives a container rebuild, not just a restart. Reset demo/test data with `docker compose down -v` or `docker volume rm multisense_backend-data`. |
| `./config/sensors.yaml` (bind, read-only) | `/config/sensors.yaml` in `ros` and `backend` | See [`config/sensors.yaml`](#configsensorsyaml) above. |

## Node parameters (ROS-level, not files)

Static per-sensor identity is exposed as ROS parameters on each
`rtsp_ingestion_node`, derived from its `config/sensors.yaml` entry at
launch time - not separately configurable, listed here for completeness
since they're inspectable at runtime (`ros2 param get /{id}_ingestion
{param}`): `sensor_id`, `modality`, `source_type`, `rtsp_url`,
`expected_fps`. `sync_status_node` exposes `tolerance_ms` (default `25.0`,
see [architecture.md](architecture.md#synchronization-measured-not-guessed)
for how that default was set).
