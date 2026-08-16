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

**v1.0-RC, issue #126**: a `poll()`/`health()` exception moves tracked
state to `DEGRADED`, not `FAILED` - and `_poll_raw()`/`health()` both
keep calling the underlying plugin every cycle while `DEGRADED`,
flipping back to `RUNNING` the moment a call succeeds (genuine
self-healing, not just "stop erroring louder"). Found live-verifying
issue #123's own "restarting the worker recovers independently"
acceptance bar: the previous behavior (`FAILED`, and `FAILED` excluded
from ever calling the plugin again) meant a transient outage - a worker
restarting for a routine deploy, an OOM-kill-and-supervisor-restart -
permanently and silently ended that connector's contribution to the
*current* session; only a brand new session's `configure()`+`start()`
(which don't special-case `DEGRADED`/`FAILED`) ever re-armed it. `FAILED`
itself is unchanged and still used exactly as before, for a
`configure()`/`start()`/`stop()` failure - those really are terminal
until an explicit fresh `start()`, unlike a `poll()`/`health()` call,
which is just as likely to be transient as permanent and there's no way
to tell the two apart except by trying again.
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
        # self-report DEGRADED without raising at all (e.g. this
        # bridge's own poll()-failure tracking). Anything other than
        # RUNNING/DEGRADED is left alone - health() is observational, it
        # shouldn't push this wrapper into a lifecycle-terminal state.
        if result.state in (ConnectorState.RUNNING, ConnectorState.DEGRADED):
            self._state = result.state
            self._last_error = result.message
        return result

    def _poll_raw(self) -> list[Any]:
        """Shared `poll()` guard - not RUNNING/DEGRADED returns an empty
        list, never raising. A `DEGRADED` connector (issue #126) keeps
        being polled every cycle rather than excluded forever like
        `FAILED`; a successful call flips it straight back to `RUNNING`.
        Type-checking of individual items is the concrete subclass's job
        (it knows which canonical type to expect)."""
        if self._state not in (ConnectorState.RUNNING, ConnectorState.DEGRADED):
            return []
        try:
            items = self._plugin.poll()
        except Exception as e:  # noqa: BLE001 - untrusted plugin code
            self._state = ConnectorState.DEGRADED
            self._last_error = str(e)
            return []
        self._state = ConnectorState.RUNNING
        self._last_error = None
        return items


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
