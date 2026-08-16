"""Generic per-sensor `SensorConnector` lifecycle wrapper (v0.9, Phase
95). Wraps one already-constructed plugin instance, enforcing the
documented lifecycle/idempotency rules
(docs/plugin-sdk.md#lifecycle-health-idempotency) and guarding every call
into plugin code - the runtime-execution counterpart to Phase 94's own
discovery-time guarding.

## Mutating calls raise; observational calls never do

`configure`/`start`/`stop` raise a clean, host-defined exception on
failure (wrapping whatever the plugin's own code raised), so a caller
(a future API endpoint, Phase 102) can handle it with ordinary
try/except - and update tracked state to `FAILED` first, so a later
`health()` call reflects the same reality even if the caller doesn't
handle the exception. `health`/`sample` never raise - they're meant to
be polled safely on a loop, so they always return a value describing
current reality (including a `FAILED` state), never another way to
crash a poller.

**v1.0-RC, issue #126**: a `sample()`/`health()` exception moves state
to `DEGRADED`, not `FAILED` - and both keep calling the underlying
plugin every cycle while `DEGRADED`, flipping back to `RUNNING` the
moment a call succeeds. Same fix, same reasoning, as
`poll_connector_instance.py`'s own docstring - found there first, then
recognized this file has the identical latching pattern (a transient
RTSP hiccup used to permanently end that sensor's connector-level
`sample()`/`health()` reporting for the rest of the session, requiring
a full `stop()`+`configure()`+`start()` cycle to recover, when the ROS
ingestion side of the exact same sensor already reconnects on its own).
`FAILED` is unchanged for `configure()`/`start()`/`stop()` failures -
those stay terminal until an explicit fresh `start()`.

## One `ConnectorInstance` per sensor_id, never a shared object

Two sensor ids using the same plugin (`ridesafe_front_rgb`/
`ridesafe_rear_rgb`, both `multisens.builtin.sensor.rtsp`) each need
their own connector *object* - `configure(sensor_id, config)` mutates
the plugin's own internal state, so two sensor ids sharing one Python
object would silently overwrite each other's configuration. Constructing
one instance per sensor id is the caller's responsibility (a future
config-driven wiring phase); this module only wraps whichever object
it's given.
"""
from __future__ import annotations

import json
from typing import Any

from app.plugins.secrets import resolve_secret_env_refs
from multisens_sdk import ConnectorConfigError, ConnectorHealth, ConnectorState, SensorConnector, SensorSample

# Heuristic, not evidence-based - same honesty treatment as tolerance_ms's
# own default (docs/evaluation.md#timestamp-matching) - a real, adjustable
# safety net giving teeth to "sample() is small/scalar-payload-only,
# never raw image/point-cloud bytes" (docs/plugin-sdk.md), not a
# precisely-derived number.
MAX_SAMPLE_PAYLOAD_BYTES = 65_536


class ConnectorRuntimeError(Exception):
    """Raised by `start()`/`stop()` when the underlying plugin's own call
    failed - wraps the plugin's original exception message."""


class ConnectorLifecycleError(Exception):
    """Raised for a lifecycle call made in the wrong state (e.g.
    `configure()` while `RUNNING`, `start()` before a successful
    `configure()`) - a caller error, never a plugin failure."""


def _payload_within_limit(payload: Any) -> bool:
    try:
        encoded = json.dumps(payload)
    except (TypeError, ValueError):
        return False
    return len(encoded.encode('utf-8')) <= MAX_SAMPLE_PAYLOAD_BYTES


class ConnectorInstance:
    def __init__(self, sensor_id: str, plugin_id: str, connector: SensorConnector):
        self.sensor_id = sensor_id
        self.plugin_id = plugin_id
        self._connector = connector
        self._state = ConnectorState.STOPPED
        self._configured = False
        self._last_error: str | None = None

    @property
    def state(self) -> ConnectorState:
        return self._state

    def configure(self, config: dict[str, Any]) -> None:
        if self._state == ConnectorState.RUNNING:
            raise ConnectorLifecycleError(f"cannot configure '{self.sensor_id}' while RUNNING - stop it first")
        resolved_config = resolve_secret_env_refs(config)
        try:
            self._connector.configure(self.sensor_id, resolved_config)
        except ConnectorConfigError:
            raise
        except Exception as e:  # noqa: BLE001 - untrusted plugin code, never left unguarded
            raise ConnectorConfigError(str(e)) from e
        self._configured = True

    def start(self) -> None:
        if self._state == ConnectorState.RUNNING:
            return  # idempotent no-op
        if not self._configured:
            raise ConnectorLifecycleError(f"cannot start '{self.sensor_id}' before configure() has succeeded")
        self._state = ConnectorState.STARTING
        try:
            self._connector.start()
        except Exception as e:  # noqa: BLE001 - untrusted plugin code
            self._state = ConnectorState.FAILED
            self._last_error = str(e)
            raise ConnectorRuntimeError(str(e)) from e
        self._state = ConnectorState.RUNNING
        self._last_error = None

    def stop(self) -> None:
        if self._state == ConnectorState.STOPPED:
            return  # idempotent no-op
        try:
            self._connector.stop()
        except Exception as e:  # noqa: BLE001 - untrusted plugin code
            self._state = ConnectorState.FAILED
            self._last_error = str(e)
            raise ConnectorRuntimeError(str(e)) from e
        self._state = ConnectorState.STOPPED
        self._last_error = None

    def health(self) -> ConnectorHealth:
        if self._state not in (ConnectorState.RUNNING, ConnectorState.DEGRADED):
            return ConnectorHealth(state=self._state, message=self._last_error)
        try:
            result = self._connector.health()
        except Exception as e:  # noqa: BLE001 - untrusted plugin code
            self._state = ConnectorState.DEGRADED
            self._last_error = str(e)
            return ConnectorHealth(state=ConnectorState.DEGRADED, message=str(e))
        # Adopt whatever the plugin itself reports rather than blindly
        # forcing RUNNING just because the call didn't raise (found live-
        # verifying issue #126's own fix) - a plugin can legitimately
        # self-report DEGRADED without raising at all (e.g.
        # builtin_rtsp.py's own connectivity check). Anything other than
        # RUNNING/DEGRADED is left alone - health() is observational, it
        # shouldn't push this wrapper into a lifecycle-terminal state.
        if result.state in (ConnectorState.RUNNING, ConnectorState.DEGRADED):
            self._state = result.state
            self._last_error = result.message
        return result

    def sample(self) -> SensorSample | None:
        """Never raises. `None` if not `RUNNING`/`DEGRADED`, if the
        plugin's own `sample()` call failed (connector moves to
        `DEGRADED` - issue #126, kept eligible to keep trying, unlike
        `FAILED`), or if a sample arrived but violated the small-payload
        contract - that last case leaves the connector `RUNNING`: an
        oversized sample is a data-quality problem with one reading, not
        a connectivity failure, and must not take down an otherwise-
        healthy connector."""
        if self._state not in (ConnectorState.RUNNING, ConnectorState.DEGRADED):
            return None
        try:
            result = self._connector.sample()
        except Exception as e:  # noqa: BLE001 - untrusted plugin code
            self._state = ConnectorState.DEGRADED
            self._last_error = str(e)
            return None
        self._state = ConnectorState.RUNNING
        self._last_error = None
        if result is None:
            return None
        if not _payload_within_limit(result.payload):
            self._last_error = (
                f"sample() payload exceeds the {MAX_SAMPLE_PAYLOAD_BYTES}-byte small-payload limit "
                f"- discarded, not forwarded (see docs/plugin-sdk.md#data-plane-vs-control-plane)"
            )
            return None
        return result
