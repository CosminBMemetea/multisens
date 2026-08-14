# multisens-example-environment-sensor

The v0.9 reference MultiSens plugin - the actual clean-room test for the
`multisens-sdk` plugin boundary. Ships two plugins in one small package:

- **`multisens.example.sensor.environment-sensor`** (`SensorConnector`) -
  a deterministic synthetic `temperature_c`/`humidity_percent` scalar
  source. Proves MultiSens is not camera-specific: this connector never
  touches ROS, RTSP, or any video concept at all.
- **`multisens.example.resource.synthetic-metric`** (`ResourceCollector`)
  - a deterministic synthetic `synthetic_metric` (unit `widgets`).

Every value either plugin produces is generated from a fixed,
deterministic pattern - **SYNTHETIC SAMPLE SOURCE**, never a real
measurement of anything.

## What this proves

This package imports **only** `multisens_sdk` (a real, separate pip
dependency) plus the Python standard library - nothing from
`backend.app`, `frontend`, or `ros2_ws` internals. See
`tests/test_boundary.py` for the automated check, and
[docs/plugin-sdk.md](../../../docs/plugin-sdk.md#reference-plugin-phase-101---shipped)
for the full write-up.

## Install and run

```bash
# From a MultiSens checkout, with multisens-sdk already installed:
pip install ./sdk
pip install ./examples/plugins/environment-sensor
```

Restart MultiSens (`docker compose restart backend`, or rebuild if
installing into the image) - the plugin discovery log line will show
`plugin discovery: N available` including these two, and (once Phase
102 ships) they'll appear on the `/integrations` page.

## Develop and test this plugin standalone

No MultiSens checkout, Docker, or ROS required - only Python and pip:

```bash
cd examples/plugins/environment-sensor
python3 -m venv .venv && source .venv/bin/activate
pip install -e ../../../sdk        # or: pip install multisens-sdk, once published
pip install -e .[testing]
pytest tests/
```
