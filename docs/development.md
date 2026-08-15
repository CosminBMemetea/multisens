# Development Guide

## Repository layout

```
multisense/
  config/sensors.yaml       # the sensor list - see docs/configuration.md
  docker-compose.yml
  .env                      # shared ROS_DOMAIN_ID / RMW_IMPLEMENTATION
  ros2_ws/                  # ROS 2 Humble workspace, one Docker image
    src/multisens_ingestion/   # generic RTSP->ROS ingestion node + launch
    src/multisens_diagnostics/ # global CPU/RAM/connected-count node
    src/multisens_sync/        # cross-sensor timestamp sync status node
  backend/                  # FastAPI + rclpy bridge, separate Docker image
    app/
    tests/
  frontend/                 # React + TS + Vite + Tailwind, separate image
    src/
  docs/                     # this directory
```

Each `ros2_ws/src/*` package is a standard ament_python ROS 2 package
(`package.xml`, `setup.py`, `resource/`) - nothing project-specific about
the layout beyond the package names.

## Running the whole stack

```bash
docker compose build
docker compose up -d
docker compose ps        # all three should reach "healthy"
```

Needs an RTSP source at the URLs in `config/sensors.yaml` - see the
[reference simulator](https://github.com/CosminBMemetea/multirtsp) or point
config at real sensors.

## Iterating on one component

**Frontend** - fastest loop, no Docker needed:
```bash
cd frontend
npm install
npm run dev          # Vite dev server, hits the backend at localhost:8000
```

**Backend** - needs ROS sourced (rclpy/diagnostic_msgs are real imports, not
optional), so local iteration without Docker requires a ROS 2 Humble
install on the host. Easiest path without one:
```bash
docker compose build backend && docker compose up -d backend
docker compose logs -f backend
```

**ROS packages** - same constraint; iterate by rebuilding the `ros` image,
or `docker exec` into a running container and re-run `colcon build` against
a bind-mounted `src/` for faster turnaround than a full image rebuild (not
currently wired into `docker-compose.yml` - the shipped image does a plain
`colcon build`, not `--symlink-install`, specifically because it's meant to
be a self-contained production image, not a dev workspace; add your own
bind mount + symlink-install locally if you want live-reload iteration).

## Running the tests

Three independent test suites, deliberately not one unified runner - each
needs a different environment, and forcing them into one command would mean
either mocking ROS/RTSP entirely (which this project has consistently
avoided) or requiring every contributor to have ROS installed just to run a
frontend test.

**Frontend** (Vitest, no Docker needed):
```bash
cd frontend
npm install
npm run test
```

**Backend** (pytest; needs `rclpy`/`diagnostic_msgs` importable, so run
inside the backend image):
```bash
docker compose build backend
docker run --rm --entrypoint bash -v "$(pwd):/repo" -w /repo/backend multisense-backend \
  -c "source /opt/ros/humble/setup.bash && pip install -r requirements-dev.txt -q && pytest"
```
Two things a naive version of this command silently gets wrong (found
while verifying issue #123's own tests): `backend/entrypoint.sh` is
`exec uvicorn ...` unconditionally, with no `exec "$@"` fallback - a
plain `docker run multisense-backend bash -c "..."` never actually runs
`bash -c`, it just starts another backend server and pytest never
executes at all (no error either - it looks like it worked). `--entrypoint
bash` is required to actually override it. Second: several demo-data
tests (`test_synthetic_demo.py` and friends) resolve `examples/` via
`Path(__file__).resolve().parents[2]`, i.e. two directories above
`backend/tests/` - that's the repo root, not `backend/` itself, so
mounting only `backend/` (`-v "$(pwd)/backend:/app"`) leaves those tests
failing with a `FileNotFoundError` for `/examples/...`. Mounting the
whole repo at `/repo` and setting the working directory to
`/repo/backend` fixes both the path and keeps `app`/`tests` importable
exactly as before.

**ROS pure-logic tests** (pytest; the modules under test - `sensor_config.py`,
`sync_logic.py` - have zero rclpy/launch_ros imports, but still need
`src/` present to import from, which the final production image
deliberately doesn't ship - see `ros2_ws/Dockerfile`'s multi-stage build.
Target the `build` stage instead, which still has `src/` and colcon
tooling):
```bash
docker build --target build -t multisense-ros-build ./ros2_ws
docker run --rm multisense-ros-build bash -c \
  "cd /workspace/src/multisens_ingestion && python3 -m pytest test && \
   cd /workspace/src/multisens_sync && python3 -m pytest test"
```
No `pip install pytest` step (found stale while verifying issue #121's own
tests) - `python3-pytest` is already present via apt, pulled in
transitively by `python3-colcon-common-extensions`
(`ros:humble-ros-base` + colcon has no `pip`/`python3-pip` at all, so a
literal `pip install` here fails outright, not just redundantly). Sourcing
`setup.bash` is also unnecessary for these two modules specifically - both
are pure-Python with zero `rclpy`/`launch_ros` imports (that's the whole
point of `test_sensor_config.py`/`test_sync_logic.py`'s own module
docstrings), so nothing here needs the ROS environment sourced.

## What's deliberately *not* tested

Per this project's own standing rule: no attempt to mock the entire ROS/RTSP
world just to raise a test count. Live RTSP ingestion, live cross-container
DDS discovery, live MJPEG relay behavior, and live dashboard rendering are
all verified by *actually running the stack* - documented step by step in
the README's phase-by-phase log and in [limitations.md](limitations.md),
not by a mocked test suite pretending to exercise them.

## Coding conventions observed (not enforced by tooling yet)

- No custom ROS messages - standard `sensor_msgs`/`diagnostic_msgs` types
  only (see [architecture.md](architecture.md#no-custom-ros-messages)).
- Every diagnostic value is either measured or explicitly `"unavailable"` -
  never a fabricated default.
- No comments explaining *what* code does (names should do that) - only
  *why*, when it's non-obvious (a workaround, a measured tradeoff, a bug
  that was found and fixed a specific way).
- Python: 4-space indent, single quotes, type hints on public/route-facing
  functions. TypeScript: `strict` mode, no `any`.

## No CI yet

Nothing here runs automatically on push. Every claim of "verified" in this
repo's history means someone actually ran it, not that a pipeline did -
see [limitations.md](limitations.md) for the honest status of that gap.
