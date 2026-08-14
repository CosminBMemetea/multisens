"""The four connector-shaped plugin contracts - new in v0.9, Phase 93.
Runtime wiring (discovery, the exception-guarded call wrapper, the
background poll/sample loop) is core-only and lives in
`backend/app/plugins/` starting Phase 94/95/97/99 - a plugin author never
imports that, only the Protocols here.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from multisens_sdk.models import GroundTruth, Prediction, ResourceObservation
from multisens_sdk.plugin import ConnectorHealth, PluginDescriptor, SensorSample


class SensorConnector(Protocol):
    """Live or recorded sensor data. `sample()` is for small/scalar
    payloads only (see `SensorSample`'s own docstring) - a streaming
    video/point-cloud connector implements `start`/`stop`/`health` and
    publishes onto the ROS sensor contract directly if it wants live
    dashboard status, never returning bytes through `sample()`."""
    def descriptor(self) -> PluginDescriptor: ...
    def configure(self, sensor_id: str, config: dict[str, Any]) -> None: ...  # raises ConnectorConfigError
    def start(self) -> None: ...      # idempotent: no-op if already RUNNING
    def stop(self) -> None: ...       # idempotent: no-op if already STOPPED, blocks until STOPPED
    def health(self) -> ConnectorHealth: ...
    def sample(self) -> SensorSample | None: ...


class PredictionConnector(Protocol):
    """Translates external algorithm output into canonical `Prediction`s.
    Pull-based: the host calls `poll()` from a background thread on a
    bounded schedule and forwards results into the existing
    `/predictions/batch` ingestion path - a connector is a code-driven
    way to call an endpoint that already exists, not a new ingestion
    mechanism."""
    def descriptor(self) -> PluginDescriptor: ...
    def configure(self, config: dict[str, Any]) -> None: ...
    def start(self) -> None: ...
    def stop(self) -> None: ...
    def health(self) -> ConnectorHealth: ...
    def poll(self) -> list[Prediction]: ...   # empty list = nothing new since last poll


class GroundTruthConnector(Protocol):
    """Translates reference annotations/measurements into canonical
    `GroundTruth`. Same pull-based shape as `PredictionConnector`."""
    def descriptor(self) -> PluginDescriptor: ...
    def configure(self, config: dict[str, Any]) -> None: ...
    def start(self) -> None: ...
    def stop(self) -> None: ...
    def health(self) -> ConnectorHealth: ...
    def poll(self) -> list[GroundTruth]: ...


@dataclass(frozen=True)
class ResourceMetricDescriptor:
    """Declares one metric a `ResourceCollector` can report. v0.7's
    `SUPPORTED_RESOURCE_METRICS` stays the built-in baseline; a
    registered collector's own `available_metrics()` values are unioned
    in at connector-registration time - a new metric like `gpu_percent`
    becomes valid only once a plugin that actually declares it is
    registered, never a permanently open vocabulary."""
    metric: str
    unit: str
    description: str = ""


class ResourceCollector(Protocol):
    """Platform/resource telemetry, extending v0.7's resource layer.
    `sample()` returns a batch of already-validated `ResourceObservation`
    rows - v0.7's own quality/unit/N/A semantics apply unchanged; a
    plugin only ever adds new rows through the existing canonical shape."""
    def descriptor(self) -> PluginDescriptor: ...
    def available_metrics(self) -> list[ResourceMetricDescriptor]: ...
    def configure(self, config: dict[str, Any]) -> None: ...
    def start(self) -> None: ...
    def sample(self) -> list[ResourceObservation]: ...
    def stop(self) -> None: ...
    def health(self) -> ConnectorHealth: ...
