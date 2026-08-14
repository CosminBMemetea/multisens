"""Lifecycle wrappers for pull-based connectors - `PredictionConnector`
and `GroundTruthConnector` (v0.9, Phase 97). Same enforcement discipline
as `connector_instance.py`'s own `ConnectorInstance` (Phase 95's
SensorConnector wrapper): mutating calls (`configure`/`start`/`stop`)
raise a clean exception on failure and move tracked state to `FAILED`
first; observational calls (`health`/`poll`) never raise.

Kept as two small classes sharing a private base, rather than unified
with `ConnectorInstance` - `SensorConnector.configure()` takes a
`sensor_id`, `PredictionConnector`/`GroundTruthConnector.configure()`
does not (neither connector is tied to one sensor; each item they emit
carries its own `sensor_ids`) - forcing one shared base across that
signature difference would cost more than it saves.

`poll()` never raises and never forwards a malformed item: an emitted
object that isn't actually a `Prediction`/`GroundTruth` instance (a
misbehaving plugin) is dropped with a recorded reason, the rest of the
same `poll()` batch still returned - the same "one bad item never
rejects the rest of an otherwise-valid batch" discipline
`insert_batch_with_partial_failure` already applies one layer down.
"""
from __future__ import annotations

from typing import Any

from app.plugins.connector_instance import ConnectorLifecycleError, ConnectorRuntimeError
from multisens_sdk import ConnectorConfigError, ConnectorHealth, ConnectorState, GroundTruth, Prediction


class _PollConnectorInstance:
    def __init__(self, plugin_id: str, plugin: Any):
        self.plugin_id = plugin_id
        self._plugin = plugin
        self._state = ConnectorState.STOPPED
        self._configured = False
        self._last_error: str | None = None

    @property
    def state(self) -> ConnectorState:
        return self._state

    def configure(self, config: dict[str, Any]) -> None:
        if self._state == ConnectorState.RUNNING:
            raise ConnectorLifecycleError(f"cannot configure '{self.plugin_id}' while RUNNING - stop it first")
        try:
            self._plugin.configure(config)
        except ConnectorConfigError:
            raise
        except Exception as e:  # noqa: BLE001 - untrusted plugin code
            raise ConnectorConfigError(str(e)) from e
        self._configured = True

    def start(self) -> None:
        if self._state == ConnectorState.RUNNING:
            return  # idempotent no-op
        if not self._configured:
            raise ConnectorLifecycleError(f"cannot start '{self.plugin_id}' before configure() has succeeded")
        self._state = ConnectorState.STARTING
        try:
            self._plugin.start()
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
            self._plugin.stop()
        except Exception as e:  # noqa: BLE001 - untrusted plugin code
            self._state = ConnectorState.FAILED
            self._last_error = str(e)
            raise ConnectorRuntimeError(str(e)) from e
        self._state = ConnectorState.STOPPED
        self._last_error = None

    def health(self) -> ConnectorHealth:
        if self._state != ConnectorState.RUNNING:
            return ConnectorHealth(state=self._state, message=self._last_error)
        try:
            return self._plugin.health()
        except Exception as e:  # noqa: BLE001 - untrusted plugin code
            self._state = ConnectorState.FAILED
            self._last_error = str(e)
            return ConnectorHealth(state=ConnectorState.FAILED, message=str(e))

    def _poll_raw(self) -> list[Any]:
        """Shared `poll()` guard - not RUNNING or the plugin's own call
        failing both return an empty list, never raising. Type-checking
        of individual items is the concrete subclass's job (it knows
        which canonical type to expect)."""
        if self._state != ConnectorState.RUNNING:
            return []
        try:
            return self._plugin.poll()
        except Exception as e:  # noqa: BLE001 - untrusted plugin code
            self._state = ConnectorState.FAILED
            self._last_error = str(e)
            return []


class PredictionConnectorInstance(_PollConnectorInstance):
    def poll(self) -> list[Prediction]:
        valid: list[Prediction] = []
        for item in self._poll_raw():
            if isinstance(item, Prediction):
                valid.append(item)
            else:
                self._last_error = f"poll() returned a non-Prediction item ({type(item).__name__}) - discarded"
        return valid


class GroundTruthConnectorInstance(_PollConnectorInstance):
    def poll(self) -> list[GroundTruth]:
        valid: list[GroundTruth] = []
        for item in self._poll_raw():
            if isinstance(item, GroundTruth):
                valid.append(item)
            else:
                self._last_error = f"poll() returned a non-GroundTruth item ({type(item).__name__}) - discarded"
        return valid
