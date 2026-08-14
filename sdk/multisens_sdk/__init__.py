"""multisens-sdk: stable, plugin-facing contracts for MultiSens external
integrations.

This module's own top-level namespace *is* the documented public API
surface (docs/plugin-sdk.md, "Public API surface" - Phase 106 finalizes
this list). Everything reachable only via a submodule import
(`multisens_sdk.models.SessionStatus`, internal helpers, ...) is not part
of the stability contract. A plugin author should only ever need:

    from multisens_sdk import (
        MULTISENS_PLUGIN_API_VERSION,
        PluginType,
        PluginDescriptor,
        ConnectorState,
        ConnectorHealth,
        SensorSample,
        PluginError,
        ConnectorConfigError,
        GroundTruth,
        Prediction,
        EvaluationResult,
        ResourceObservation,
        MetricValue,
        ResourceQuality,
        MatchResult,
        MatchedPair,
        EvaluatorOutput,
        EvaluatorPlugin,
        MetricDescriptor,
        SensorConnector,
        PredictionConnector,
        GroundTruthConnector,
        ResourceCollector,
        ResourceMetricDescriptor,
    )
"""
from multisens_sdk.connectors import (
    GroundTruthConnector,
    PredictionConnector,
    ResourceCollector,
    ResourceMetricDescriptor,
    SensorConnector,
)
from multisens_sdk.evaluators import EvaluatorOutput, EvaluatorPlugin, MetricDescriptor
from multisens_sdk.matching import MatchedPair, MatchResult
from multisens_sdk.models import (
    EvaluationResult,
    GroundTruth,
    MetricValue,
    Prediction,
    ResourceObservation,
    ResourceQuality,
)
from multisens_sdk.plugin import (
    MULTISENS_PLUGIN_API_VERSION,
    ConnectorConfigError,
    ConnectorHealth,
    ConnectorState,
    PluginDescriptor,
    PluginError,
    PluginType,
    SensorSample,
)

__all__ = [
    'MULTISENS_PLUGIN_API_VERSION',
    'PluginType',
    'PluginDescriptor',
    'PluginError',
    'ConnectorConfigError',
    'ConnectorState',
    'ConnectorHealth',
    'SensorSample',
    'GroundTruth',
    'Prediction',
    'EvaluationResult',
    'ResourceObservation',
    'ResourceQuality',
    'MetricValue',
    'MatchResult',
    'MatchedPair',
    'EvaluatorOutput',
    'EvaluatorPlugin',
    'MetricDescriptor',
    'SensorConnector',
    'PredictionConnector',
    'GroundTruthConnector',
    'ResourceCollector',
    'ResourceMetricDescriptor',
]
