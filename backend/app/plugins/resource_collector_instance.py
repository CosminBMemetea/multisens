"""Lifecycle wrapper for `ResourceCollector` plugins (v0.9, Phase 99).
Same enforcement discipline as every other connector-shaped wrapper in
this package: mutating calls (`configure`/`start`/`stop`) raise a clean
exception on failure and move tracked state to `FAILED` first;
observational calls (`health`/`sample`) never raise. `sample()` filters
out anything that isn't actually a `ResourceObservation` (a misbehaving
plugin), the same "one bad item never rejects the rest of a batch"
discipline `poll_connector_instance.py` already applies.

**v1.0-RC, issue #126**: same fix as `poll_connector_instance.py`'s own
docstring - a `sample()`/`health()` exception moves state to `DEGRADED`,
not `FAILED`, and both keep calling the plugin every cycle while
`DEGRADED`, flipping back to `RUNNING` the moment a call succeeds.
`FAILED` is unchanged for `configure()`/`start()`/`stop()` failures.
"""
from __future__ import annotations

from typing import Any

from app.plugins.connector_instance import ConnectorLifecycleError, ConnectorRuntimeError
from multisens_sdk import ConnectorConfigError, ConnectorHealth, ConnectorState, ResourceObservation


class ResourceCollectorInstance:
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
        if self._state not in (ConnectorState.RUNNING, ConnectorState.DEGRADED):
            return ConnectorHealth(state=self._state, message=self._last_error)
        try:
            result = self._plugin.health()
        except Exception as e:  # noqa: BLE001 - untrusted plugin code
            self._state = ConnectorState.DEGRADED
            self._last_error = str(e)
            return ConnectorHealth(state=ConnectorState.DEGRADED, message=str(e))
        # Adopt whatever the plugin itself reports rather than blindly
        # forcing RUNNING just because the call didn't raise (found live-
        # verifying issue #126's own fix) - a plugin can legitimately
        # self-report DEGRADED without raising at all. Anything other
        # than RUNNING/DEGRADED is left alone - health() is
        # observational, it shouldn't push this wrapper into a
        # lifecycle-terminal state.
        if result.state in (ConnectorState.RUNNING, ConnectorState.DEGRADED):
            self._state = result.state
            self._last_error = result.message
        return result

    def sample(self) -> list[ResourceObservation]:
        """Never raises. `[]` if not `RUNNING`/`DEGRADED` or the plugin's
        own `sample()` call failed (connector moves to `DEGRADED` - issue
        #126, kept eligible to keep trying, unlike `FAILED`); a
        non-`ResourceObservation` item in the returned list is dropped
        with a recorded reason, the rest of the same batch still
        returned."""
        if self._state not in (ConnectorState.RUNNING, ConnectorState.DEGRADED):
            return []
        try:
            results = self._plugin.sample()
        except Exception as e:  # noqa: BLE001 - untrusted plugin code
            self._state = ConnectorState.DEGRADED
            self._last_error = str(e)
            return []
        self._state = ConnectorState.RUNNING
        self._last_error = None
        valid: list[ResourceObservation] = []
        for item in results:
            if isinstance(item, ResourceObservation):
                valid.append(item)
            else:
                self._last_error = f"sample() returned a non-ResourceObservation item ({type(item).__name__}) - discarded"
        return valid
