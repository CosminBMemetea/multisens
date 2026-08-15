"""Builds real `ConnectorInstance`s from `config/sensors.yaml`'s optional
per-sensor `connector:` block (v0.9, Phase 102) - the wiring
docs/connector-api.md already documented back in Phase 95 but nothing
had yet executed. Runs once at startup (see `app/main.py`'s lifespan);
there is no mutation API (issue #103's own explicit "config stays a
restart-time file change" boundary) - a connector's config only ever
changes by editing the file and restarting the container.

One fresh plugin object per sensor id, never a shared one - `plugin_id`
names an *implementation*, not an instance, so two sensor ids naming the
same `plugin_id` (two RTSP cameras) each get their own object via the
registry's own `PluginRecord.factory` (Phase 102's own addition to
`registry.py`). A sensor whose connector can't be built at all (unknown
plugin, wrong plugin_type, not AVAILABLE) is skipped with a printed
diagnostic - it never prevents the rest of the sensors' connectors from
being built, nor crashes application startup.

`build_poll_runners()`/`stop_poll_runners()` (v0.9 bug hunt, issue #110)
close a real gap the same discipline above didn't: Phase 97 built
`PollRunner`/`PredictionConnectorInstance`/`GroundTruthConnectorInstance`
and tested them thoroughly in isolation, but nothing ever called them -
a `PREDICTION_CONNECTOR`/`GROUND_TRUTH_CONNECTOR` plugin would discover
as `AVAILABLE` and then sit inert forever. Same wiring shape as sensor
connectors (`poll_connectors:` config list, factory-per-entry, one bad
entry never blocks the rest), except each entry also gets its own
background `PollRunner` thread started immediately, since a poll
connector's whole purpose - unlike a sensor connector, which is polled
on demand through `/api/connectors` - is to run continuously.

`build_resource_collector_instances()`/`start_resource_collection()`/
`stop_resource_collection()` (v0.9.1, issue #111) close the last gap of
this kind: `ResourceCollectorInstance` (Phase 99) and the pre-existing
v0.7 built-in collector had no live trigger at all. Deliberately NOT the
same one-shot "build once at boot" shape as everything above - a
resource collector's whole point is to measure one controlled
experiment, so it's split into a boot-time construction step (this
module) and a per-session start/stop step, called from
`app/api/sessions.py`'s `start_session`/`complete_session`.
"""
from __future__ import annotations

from typing import Any

from app.persistence import repository as repo
from app.plugins.connector_instance import ConnectorInstance, ConnectorLifecycleError, ConnectorRuntimeError
from app.plugins.poll_connector_instance import GroundTruthConnectorInstance, PredictionConnectorInstance
from app.plugins.poll_runner import DEFAULT_POLL_INTERVAL_S, PollRunner
from app.plugins.registry import PluginRegistry, PluginStatus
from app.plugins.resource_collector_instance import ResourceCollectorInstance
from multisens_sdk import ConnectorConfigError, PluginType


def build_connector_instances(sensors: list[dict], registry: PluginRegistry) -> dict[str, ConnectorInstance]:
    instances: dict[str, ConnectorInstance] = {}
    for sensor in sensors:
        connector_spec = sensor.get('connector')
        if not isinstance(connector_spec, dict):
            continue  # no connector block - this sensor stays video-plane/ROS-only, unchanged

        sensor_id = sensor.get('id')
        plugin_id = connector_spec.get('plugin')
        config = connector_spec.get('config', {})
        if not isinstance(sensor_id, str) or not isinstance(plugin_id, str):
            print(f"connector wiring: sensor entry missing 'id' or connector.plugin - skipped ({sensor!r})")
            continue

        record = registry.get(plugin_id)
        if record is None or record.status != PluginStatus.AVAILABLE:
            status = record.status.value if record is not None else 'not found'
            print(f"connector wiring: sensor '{sensor_id}' names plugin '{plugin_id}' ({status}) - skipped")
            continue
        if record.descriptor is None or record.descriptor.plugin_type != PluginType.SENSOR_CONNECTOR:
            print(f"connector wiring: sensor '{sensor_id}' names plugin '{plugin_id}' which is not a sensor "
                  f"connector - skipped")
            continue
        if record.factory is None:
            print(f"connector wiring: sensor '{sensor_id}' plugin '{plugin_id}' has no usable factory - skipped")
            continue

        connector_obj = record.factory()
        instance = ConnectorInstance(sensor_id, plugin_id, connector_obj)
        instances[sensor_id] = instance

        try:
            instance.configure(dict(config) if isinstance(config, dict) else {})
            instance.start()
        except (ConnectorConfigError, ConnectorRuntimeError, ConnectorLifecycleError) as e:
            # Left registered in `instances` (STOPPED if configure() itself
            # rejected the config, FAILED if configure() succeeded but
            # start() didn't) rather than dropped - GET
            # /api/connectors/{sensor_id} must still be able to show *why*
            # it isn't running, never a silent 404 for a sensor that
            # really is named in config.
            print(f"connector wiring: sensor '{sensor_id}' plugin '{plugin_id}' failed to start: {e}")

    return instances


def stop_connector_instances(instances: dict[str, ConnectorInstance]) -> None:
    """The shutdown-time counterpart to `build_connector_instances()`
    (v0.9, Phase 105 robustness review - extracted out of `main.py`'s
    lifespan so this has a dedicated test, same reasoning as
    `build_connector_instances()` itself). One misbehaving plugin's
    `stop()` failure is printed and skipped, never allowed to block the
    rest of shutdown - the same failure-isolation discipline every other
    plugin call site in this package already follows."""
    for instance in instances.values():
        try:
            instance.stop()
        except ConnectorRuntimeError as e:
            print(f"connector shutdown: sensor '{instance.sensor_id}' failed to stop cleanly: {e}")


_POLL_CONNECTOR_TYPES = {
    PluginType.PREDICTION_CONNECTOR: (PredictionConnectorInstance, repo.insert_predictions_batch),
    PluginType.GROUND_TRUTH_CONNECTOR: (GroundTruthConnectorInstance, repo.insert_ground_truth_batch),
}


def build_poll_runners(
    poll_connectors: list[dict], registry: PluginRegistry, *, connect: Any = None,
) -> dict[str, tuple[Any, PollRunner]]:
    """Reads the `poll_connectors:` config list (`app/config.py`'s
    `load_poll_connectors()`), wires each entry into a real
    `PredictionConnectorInstance`/`GroundTruthConnectorInstance` plus a
    started `PollRunner` background thread. Returns `{connector_id:
    (instance, runner)}` - both kept (not just the runner) so
    `stop_poll_runners()` can cleanly stop the connector itself, not
    only the polling thread.

    `connect` is forwarded to each `PollRunner` verbatim when given -
    purely for tests, so they can point every runner at one real
    temporary database instead of `MULTISENS_DB_PATH`, the same
    injectable-connect pattern `PollRunner` itself already establishes;
    `None` (the default) lets each `PollRunner` fall back to its own
    default connection."""
    runners: dict[str, tuple[Any, PollRunner]] = {}
    for spec in poll_connectors:
        connector_id = spec.get('id')
        plugin_id = spec.get('plugin')
        config = spec.get('config', {})
        poll_interval_s = spec.get('poll_interval_s', DEFAULT_POLL_INTERVAL_S)
        if not isinstance(connector_id, str) or not isinstance(plugin_id, str):
            print(f"poll connector wiring: entry missing 'id' or 'plugin' - skipped ({spec!r})")
            continue

        record = registry.get(plugin_id)
        if record is None or record.status != PluginStatus.AVAILABLE:
            status = record.status.value if record is not None else 'not found'
            print(f"poll connector wiring: '{connector_id}' names plugin '{plugin_id}' ({status}) - skipped")
            continue
        if record.descriptor is None or record.descriptor.plugin_type not in _POLL_CONNECTOR_TYPES:
            print(f"poll connector wiring: '{connector_id}' names plugin '{plugin_id}' which is not a "
                  f"prediction/ground-truth connector - skipped")
            continue
        if record.factory is None:
            print(f"poll connector wiring: '{connector_id}' plugin '{plugin_id}' has no usable factory - skipped")
            continue
        # `not (x > 0)` rather than `x <= 0` - deliberately NaN-safe: every
        # comparison against NaN is False in Python, so `nan <= 0` would
        # be False and let a NaN interval slip through to
        # threading.Event.wait(timeout=nan) (PyYAML's SafeLoader accepts
        # the YAML 1.1 `.nan` literal, so this is a real reachable config
        # value, not a hypothetical one) - `not (nan > 0)` is True,
        # correctly rejecting it same as any other non-positive value.
        if not isinstance(poll_interval_s, (int, float)) or isinstance(poll_interval_s, bool) \
                or not (poll_interval_s > 0):
            print(f"poll connector wiring: '{connector_id}' has an invalid poll_interval_s "
                  f"({poll_interval_s!r}) - skipped")
            continue

        instance_cls, bulk_insert = _POLL_CONNECTOR_TYPES[record.descriptor.plugin_type]
        instance = instance_cls(plugin_id, record.factory())

        try:
            instance.configure(dict(config) if isinstance(config, dict) else {})
            instance.start()
        except (ConnectorConfigError, ConnectorRuntimeError, ConnectorLifecycleError) as e:
            # Unlike build_connector_instances() above, a poll connector
            # that never reaches RUNNING has nothing to run - there is no
            # equivalent of /api/connectors/{id} for poll connectors to
            # show a FAILED reason through, so it's dropped rather than
            # kept inert; the print() line is the only record.
            print(f"poll connector wiring: '{connector_id}' plugin '{plugin_id}' failed to start: {e}")
            continue

        runner_kwargs: dict[str, Any] = {'poll_interval_s': poll_interval_s}
        if connect is not None:
            runner_kwargs['connect'] = connect
        runner = PollRunner(poll=instance.poll, bulk_insert=bulk_insert, **runner_kwargs)
        runner.start()
        runners[connector_id] = (instance, runner)

    return runners


def stop_poll_runners(runners: dict[str, tuple[Any, PollRunner]]) -> None:
    """The shutdown-time counterpart to `build_poll_runners()` - stops
    each background thread first (so no poll is in flight against a
    connector that's about to be stopped), then the connector itself.
    One misbehaving `stop()` is printed and skipped, never allowed to
    block the rest of shutdown, matching `stop_connector_instances()`."""
    for connector_id, (instance, runner) in runners.items():
        runner.stop()
        try:
            instance.stop()
        except ConnectorRuntimeError as e:
            print(f"poll connector shutdown: '{connector_id}' failed to stop cleanly: {e}")


# --- resource collectors (v0.9.1, issue #111): session-bound, not boot-bound
#
# Unlike everything above - a sensor/poll connector is built once and runs
# for the whole container lifetime - a resource collector's whole point is
# to measure one controlled experiment (docs/resources.md's own
# "configuration attribution is temporal association" rule). So this is
# split into two steps instead of one `build_*` function:
#
#   build_resource_collector_instances() - boot time, from `resource_collectors:`
#     config. Constructs each `ResourceCollectorInstance` but never calls
#     configure()/start() - there is no session yet, nothing to attribute
#     observations to.
#   start_resource_collection()/stop_resource_collection() - called from
#     the session /start and /complete API handlers, per session.

def build_resource_collector_instances(
    resource_collectors: list[dict], registry: PluginRegistry,
) -> dict[str, tuple[ResourceCollectorInstance, dict, float]]:
    """Returns `{collector_id: (instance, static_config, poll_interval_s)}`
    - the static YAML `config:` block and interval are kept alongside the
    instance because `configure()` is called again per-session (merged
    with session_id/configuration_id/platform_id/sensor_ids), not once
    here. Same skip-and-continue failure isolation as
    `build_connector_instances()`/`build_poll_runners()` - one bad entry
    never blocks the rest."""
    instances: dict[str, tuple[ResourceCollectorInstance, dict, float]] = {}
    for spec in resource_collectors:
        collector_id = spec.get('id')
        plugin_id = spec.get('plugin')
        config = spec.get('config', {})
        poll_interval_s = spec.get('poll_interval_s', DEFAULT_POLL_INTERVAL_S)
        if not isinstance(collector_id, str) or not isinstance(plugin_id, str):
            print(f"resource collector wiring: entry missing 'id' or 'plugin' - skipped ({spec!r})")
            continue

        record = registry.get(plugin_id)
        if record is None or record.status != PluginStatus.AVAILABLE:
            status = record.status.value if record is not None else 'not found'
            print(f"resource collector wiring: '{collector_id}' names plugin '{plugin_id}' ({status}) - skipped")
            continue
        if record.descriptor is None or record.descriptor.plugin_type != PluginType.RESOURCE_COLLECTOR:
            print(f"resource collector wiring: '{collector_id}' names plugin '{plugin_id}' which is not a "
                  f"resource collector - skipped")
            continue
        if record.factory is None:
            print(f"resource collector wiring: '{collector_id}' plugin '{plugin_id}' has no usable factory - skipped")
            continue
        if not isinstance(poll_interval_s, (int, float)) or isinstance(poll_interval_s, bool) \
                or not (poll_interval_s > 0):
            print(f"resource collector wiring: '{collector_id}' has an invalid poll_interval_s "
                  f"({poll_interval_s!r}) - skipped")
            continue

        instance = ResourceCollectorInstance(plugin_id, record.factory())
        instances[collector_id] = (instance, dict(config) if isinstance(config, dict) else {}, poll_interval_s)

    return instances


def start_resource_collection(
    session_id: str, configuration_id: str | None, platform_id: str | None, sensor_ids: list[str],
    collectors: dict[str, tuple[ResourceCollectorInstance, dict, float]], *, connect: Any = None,
) -> dict[str, tuple[ResourceCollectorInstance, PollRunner]]:
    """Configures and starts every collector built by
    `build_resource_collector_instances()` for one session, each with its
    own `PollRunner` sampling loop - `ResourceCollectorInstance.sample()`
    already matches `PollRunner`'s own `poll: Callable[[], list[Any]]`
    shape exactly (never raises, returns `list[ResourceObservation]`), so
    this reuses `PollRunner` unmodified rather than a second runner class.

    A collector that fails to start (e.g. `ConnectorLifecycleError`
    because it's already `RUNNING` for a *different*, still-in-progress
    session - `ResourceCollectorInstance.configure()`'s own guard) is
    printed and skipped, never raised - a resource-collector problem must
    never fail session start itself (docs/resources.md's own "the
    resource layer must never corrupt session state" posture). Callers
    that need to know *why* a given collector isn't attached to this
    session read `GET /api/resource-collectors` afterward, rather than
    session /start growing a parallel status shape of its own.

    `connect` is forwarded to each `PollRunner` verbatim when given -
    same test-only injectable-connect convention `build_poll_runners()`
    already establishes."""
    runners: dict[str, tuple[ResourceCollectorInstance, PollRunner]] = {}
    for collector_id, (instance, static_config, poll_interval_s) in collectors.items():
        config = {
            **static_config, 'session_id': session_id, 'configuration_id': configuration_id,
            'platform_id': platform_id, 'sensor_ids': sensor_ids,
        }
        try:
            instance.configure(config)
            instance.start()
        except (ConnectorConfigError, ConnectorRuntimeError, ConnectorLifecycleError) as e:
            print(f"resource collection: '{collector_id}' failed to start for session '{session_id}': {e}")
            continue

        runner_kwargs: dict[str, Any] = {'poll_interval_s': poll_interval_s}
        if connect is not None:
            runner_kwargs['connect'] = connect
        runner = PollRunner(poll=instance.sample, bulk_insert=repo.insert_resource_observations_batch, **runner_kwargs)
        runner.start()
        runners[collector_id] = (instance, runner)

    return runners


def stop_resource_collection(runners: dict[str, tuple[ResourceCollectorInstance, PollRunner]]) -> None:
    """The session-/complete counterpart to `start_resource_collection()` -
    same stop-runner-then-stop-instance order and one-failure-never-blocks
    -the-rest discipline as `stop_poll_runners()`."""
    for collector_id, (instance, runner) in runners.items():
        runner.stop()
        try:
            instance.stop()
        except ConnectorRuntimeError as e:
            print(f"resource collection shutdown: '{collector_id}' failed to stop cleanly: {e}")
