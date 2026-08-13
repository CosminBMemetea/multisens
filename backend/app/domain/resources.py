"""Resource-observation domain model (v0.7, Phase 64).

Shape only - Phase 64's own acceptance criteria are explicit that no
algorithm code belongs here yet (validation: Phase 65; collection: Phase
66; summaries: Phase 67; comparability/trade-off joining: Phase 68;
constraints/Pareto: Phase 69). This module exists so every later phase
builds against one already-reviewed shape, not an implicit one.

Transport-agnostic like every other domain module - no fastapi, sqlite3,
rclpy, or psutil import. `ResourceObservation` is a pydantic `BaseModel`
like `GroundTruth`/`Prediction` (models.py), not a plain dataclass like
decision.py's `ConfigurationEvidence`/`ConfigurationDecision` - the
distinction that matters is persisted/ingested evidence (pydantic, this
module) versus pure in-memory computation artifacts (dataclass,
decision.py's own types and this module's later-phase
`ConfigurationResourceProfile`/`ConfigurationTradeoff`).

## Why a resource observation is not just another diagnostics stream

v0.1's `system_diagnostics_node` already measures `cpu_percent`/
`memory_percent` via psutil, continuously, forever, streamed live over
`/multisens/diagnostics` -> WebSocket -> dashboard. That mechanism is
correct for what it does but wrong for what v0.7 needs: it has no
time-window concept (a resource observation must be scoped to one
session's start/stop), no persistence (a resource observation must
survive restart to support before/after comparison), and no
configuration attribution (it is a single host-wide number, never "this
number, because these sensors were active"). Phase 66's collector will
call the *same* underlying psutil primitives system_diagnostics_node
already uses - reusing the measurement, not duplicating it - but wrap
them in a new, session-window-aware, persisting mechanism. See
docs/decision-support.md and the v0.7 architecture review (issue #65)
for the full reasoning.

## Configuration attribution is temporal association, not process isolation

Without per-configuration process isolation on a shared host, "this CPU
reading belongs to configuration X" can only ever mean "X was the
configuration actively running while this window was measured" - never
a rigorous causal or isolated cost. `ResourceObservation.configuration_id`
records exactly that association, nothing stronger. Every surface that
renders a resource number must carry this caveat, not just this
docstring - see docs/resources.md (Phase 77).

## Persistence: bounded periodic summary rows, not raw samples

A `ResourceObservation` row is already a small pre-aggregated window (a
collector samples repeatedly for ~5-10s and folds the result into one
row, `sample_count` recording how many samples went in) - there is no
separate raw-sample table in v0.7. A "resource over time" chart is the
sequence of these rows for one `(session_id, configuration_id, metric)`;
a whole-session summary (mean/median/p95/min/max, Phase 67) is a pure
computed aggregation *over* those persisted rows at read time, never a
second stored source of truth - same pattern `aggregate_requirement_results`
already uses for `RequirementResult`. This is a deliberate, narrow
exception to this project's "recompute, never persist" norm: unlike a
`RequirementResult`, a resource-measurement window cannot be recomputed
later once the window has passed, so the summary row itself has to be
the persisted artifact.

## Session, not a new ResourceMeasurementRun entity

`Session.id` plus each observation's own `started_at`/`ended_at`
sub-window is sufficient to answer "was this measured during session X,
over what window" - no new entity. Revisit only if a real need for
several independent measurement windows within one session, that
`Session`'s own fields cannot express, actually shows up.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

# Every value has an explicit provenance - never just a number.
#
#   - MEASURED: captured directly by a v0.7 collector during the
#     experiment (psutil calls, or the existing fps_received/
#     publish_latency_ms diagnostics reused as-is). Always preferred.
#   - DECLARED: a human-supplied hardware/property value (e.g. "this
#     camera's nominal bitrate is 5 Mbps"), not measured this session.
#     Coexists with a MEASURED row for the same metric without
#     auto-reconciliation - same "never silently merge two evidence
#     sources" discipline EvidenceBinding already established (v0.4).
#   - ESTIMATED: computed from an explicit, visible formula over
#     MEASURED/DECLARED values (`source` names the formula verbatim,
#     e.g. "estimated: bitrate_mbps * duration_hours"). Never an opaque
#     second estimate with no visible inputs.
#   - UNAVAILABLE: no reliable value exists. `value` is None. Reported
#     as an explicit row, never silently dropped - same "NO EVIDENCE,
#     always reported" discipline v0.6's decision layer established.
#     Never coerced to 0.0, which would claim a measurement that never
#     happened (same "unavailable is not zero" rule v0.1's diagnostics
#     already follows for frames_dropped).
ResourceQuality = Literal['measured', 'declared', 'estimated', 'unavailable']

# The v0.7 supported metric vocabulary - deliberately small (architecture
# review, "keep v0.7 small"). Each is genuinely obtainable today, either
# via a new session-scoped collector reusing existing psutil primitives
# (cpu_percent, memory_mb, network_receive_mbps, network_transmit_mbps)
# or by reusing an existing per-sensor diagnostic field outright (fps ==
# fps_received, pipeline_latency_ms == publish_latency_ms, renamed only
# for clarity - not a new measurement).
#
# GPU/power/temperature/storage-write are deliberately NOT in this set:
# no discrete-GPU passthrough and no Jetson exist in the current dev
# environment, so shipping those collectors now would mean code no one
# can exercise or verify (architecture review, "what I would remove").
# storage-write specifically is never measured in v0.7 at all - storage
# is an ESTIMATED derived quantity (bitrate x duration, a later phase),
# never a disk-IO collector.
#
# `ResourceObservation.metric` itself stays a plain `str`, not this
# Literal - same open-vocabulary posture `AcceptanceCriterion.metric`
# already has (profiles.py). This constant is the API-boundary
# validation reference (Phase 70), not a domain-layer enum.
SUPPORTED_RESOURCE_METRICS: dict[str, str] = {
    'cpu_percent': '%',
    'memory_mb': 'MB',
    'network_receive_mbps': 'Mbps',
    'network_transmit_mbps': 'Mbps',
    'fps': 'fps',
    'pipeline_latency_ms': 'ms',
}


class ResourceObservation(BaseModel):
    """One measured/declared/estimated/unavailable value for one metric,
    over one time window, optionally attributed to one configuration.
    Persisted (v0.7, Phase 65) - the ingested-evidence shape, not a
    computed artifact; see this module's own docstring for why that
    makes it a pydantic BaseModel like GroundTruth/Prediction rather
    than a decision.py-style dataclass."""
    id: str
    session_id: str
    # None only for a genuinely unattributed/system-wide reading -
    # reported explicitly, never guessed at. See "configuration
    # attribution is temporal association" above for what a non-None
    # value actually means (and does not mean).
    configuration_id: str | None = None
    metric: str
    # None iff quality == 'unavailable' - enforced starting Phase 65,
    # not here. 0.0 is a valid, distinct measured value, never confused
    # with "no value."
    value: float | None
    unit: str
    quality: ResourceQuality
    # Always populated, never blank even for a measured row - e.g.
    # 'psutil.cpu_percent', 'user_declared', or an ESTIMATED row's exact
    # formula. Free text by design, not a closed enum - mirrors
    # RequirementResult.reasons's own free-text-with-a-real-value
    # posture.
    source: str
    platform_id: str
    started_at: datetime
    ended_at: datetime
    # How many individual samples this row folds together - 1 for a
    # true point sample, >1 for a collector's periodic summary window
    # (see "persistence" above). Always >= 1, even for an UNAVAILABLE
    # row (the collector still attempted at least one sample).
    sample_count: int = 1
    metadata: dict[str, Any] = Field(default_factory=dict)


class ExecutionPlatform(BaseModel):
    """The compute context a resource observation was measured under -
    e.g. 'Apple M2, Docker Desktop' vs. 'Jetson Orin, Ubuntu'. A small,
    explicitly-declared record (like config/sensors.yaml's own posture:
    declared, never auto-detected by magic), not a database table -
    realistically 1-3 platforms will ever exist for this project. Zero
    NVIDIA/Apple-specific fields anywhere - a future GPU metric is just
    another entry in SUPPORTED_RESOURCE_METRICS collected by a
    platform-specific collector that returns 'unavailable' where it
    doesn't apply, never a branch on vendor in this model."""
    id: str
    display_name: str
    architecture: str
    os: str
    metadata: dict[str, Any] = Field(default_factory=dict)


# Fallback platform id for any observation whose collector could not
# determine a real ExecutionPlatform - never silently None (every
# ResourceObservation.platform_id is always populated), but honestly
# named so a comparability check (Phase 68) can treat it as never
# comparable to anything, including itself.
UNKNOWN_PLATFORM_ID = 'unknown'
