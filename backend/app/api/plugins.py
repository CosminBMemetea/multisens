"""Read-only plugin/connector visibility API (v0.9, Phase 102, issue
#103). Deliberately never a marketplace: no install/uninstall/start/stop
route exists anywhere in this router, matching the master prompt's own
explicit "installation stays external package/deployment management"
boundary - a plugin's presence and a connector's running state are both
entirely decided at container startup (`app/plugins/registry.py`'s
discovery, `app/plugins/manager.py`'s config-driven wiring), never by a
call to this API.

Every response here is passed through `redact_secrets` before leaving
the process - `capabilities`, connector `config`, and `health.details`
can each carry a plugin-supplied dict that might contain a secret-shaped
key, regardless of whether the underlying config used a literal value or
the `*_env` reference convention (see `app/plugins/secrets.py`).
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.config import load_sensors
from app.plugins import state as plugin_state
from app.plugins.registry import PluginRecord, PluginStatus
from app.plugins.secrets import redact_secrets
from multisens_sdk import PluginType

router = APIRouter(prefix='/api', tags=['plugins'])


class PluginSummary(BaseModel):
    plugin_id: str
    name: str | None
    version: str | None
    plugin_type: PluginType | None
    status: PluginStatus
    distribution_name: str | None
    distribution_version: str | None
    error: str | None


def _to_summary(record: PluginRecord) -> PluginSummary:
    return PluginSummary(
        plugin_id=record.plugin_id,
        name=record.descriptor.name if record.descriptor is not None else None,
        version=record.descriptor.version if record.descriptor is not None else None,
        plugin_type=record.descriptor.plugin_type if record.descriptor is not None else None,
        status=record.status,
        distribution_name=record.distribution_name,
        distribution_version=record.distribution_version,
        error=record.error,
    )


class PluginDetail(PluginSummary):
    api_version: str | None
    author: str | None
    license: str | None
    description: str | None
    homepage: str | None
    capabilities: dict[str, Any]


def _to_detail(record: PluginRecord) -> PluginDetail:
    descriptor = record.descriptor
    return PluginDetail(
        **_to_summary(record).model_dump(),
        api_version=descriptor.api_version if descriptor is not None else None,
        author=descriptor.author if descriptor is not None else None,
        license=descriptor.license if descriptor is not None else None,
        description=descriptor.description if descriptor is not None else None,
        homepage=descriptor.homepage if descriptor is not None else None,
        capabilities=redact_secrets(descriptor.capabilities) if descriptor is not None else {},
    )


def _require_plugin(plugin_id: str) -> PluginRecord:
    record = plugin_state.plugin_registry.get(plugin_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"plugin '{plugin_id}' not found")
    return record


@router.get('/plugins')
def list_plugins() -> list[PluginSummary]:
    return [_to_summary(r) for r in plugin_state.plugin_registry.records.values()]


@router.get('/plugins/{plugin_id}')
def get_plugin(plugin_id: str) -> PluginDetail:
    return _to_detail(_require_plugin(plugin_id))


@router.get('/plugins/{plugin_id}/capabilities')
def get_plugin_capabilities(plugin_id: str) -> dict[str, Any]:
    record = _require_plugin(plugin_id)
    if record.descriptor is None:
        return {}
    return redact_secrets(record.descriptor.capabilities)


class ConnectorHealthResponse(BaseModel):
    state: str
    last_sample_age_s: float | None
    message: str | None
    details: dict[str, Any]


class ConnectorSummary(BaseModel):
    sensor_id: str
    plugin_id: str
    state: str
    config: dict[str, Any]


class ConnectorDetail(ConnectorSummary):
    health: ConnectorHealthResponse


def _connector_config(sensor_id: str) -> dict[str, Any]:
    """The raw `connector.config` block from config/sensors.yaml, for
    display only - never re-resolved (`*_env` refs stay unresolved
    references here, redacted like everything else) and never the live
    plugin's own internal state."""
    for sensor in load_sensors():
        if sensor.get('id') == sensor_id:
            connector_spec = sensor.get('connector')
            if isinstance(connector_spec, dict) and isinstance(connector_spec.get('config'), dict):
                return connector_spec['config']
    return {}


def _to_connector_summary(sensor_id: str, instance: Any) -> ConnectorSummary:
    return ConnectorSummary(
        sensor_id=sensor_id, plugin_id=instance.plugin_id, state=instance.state.value,
        config=redact_secrets(_connector_config(sensor_id)),
    )


def _to_connector_detail(sensor_id: str, instance: Any) -> ConnectorDetail:
    health = instance.health()
    return ConnectorDetail(
        **_to_connector_summary(sensor_id, instance).model_dump(),
        health=ConnectorHealthResponse(
            state=health.state.value, last_sample_age_s=health.last_sample_age_s,
            message=health.message, details=redact_secrets(health.details),
        ),
    )


@router.get('/connectors')
def list_connectors() -> list[ConnectorSummary]:
    return [_to_connector_summary(sensor_id, instance) for sensor_id, instance in plugin_state.connector_instances.items()]


@router.get('/connectors/{sensor_id}')
def get_connector(sensor_id: str) -> ConnectorDetail:
    instance = plugin_state.connector_instances.get(sensor_id)
    if instance is None:
        raise HTTPException(status_code=404, detail=f"no connector configured for sensor '{sensor_id}'")
    return _to_connector_detail(sensor_id, instance)
