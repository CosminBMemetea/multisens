"""`EvaluatorOutput`/`EvaluatorPlugin` - relocated from
`backend/app/domain/evaluator_output.py` (v0.9, Phase 93). Same shapes the
v0.8 `Evaluator`/`EvaluatorOutput` protocol already had; `Evaluator` is kept
as an alias so every existing backend import (`from app.domain.evaluators
import Evaluator, EvaluatorOutput`) is unaffected.

`descriptor()` was added in Phase 94 - a real, deliberate correction: the
other four connector contracts all had `descriptor()` from Phase 93
onward (needed for the plugin registry to treat every plugin type
uniformly, one global id namespace, one discovery/compatibility path),
but `EvaluatorPlugin` didn't yet, since Phase 93 only relocated the
existing v0.8 shape verbatim. Phase 94's registry needs every plugin type
- including the three built-in evaluators - to expose a `PluginDescriptor`,
so this method was added here rather than inventing a separate,
evaluator-specific registration path.

`MetricDescriptor` is defined here but not yet part of the
`EvaluatorPlugin` protocol itself - Phase 98 adds a `metric_descriptors()`
method to the protocol and wires it through the registry. Defining the
shape now, in the same phase as the other SDK contracts, avoids Phase 98
needing to touch this module's own import surface.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Protocol

from multisens_sdk.matching import MatchResult
from multisens_sdk.models import MetricValue
from multisens_sdk.plugin import PluginDescriptor


@dataclass
class EvaluatorOutput:
    """What any `EvaluatorPlugin.evaluate()` call returns - the same shape
    `EvaluationResult` persists, regardless of which evaluator produced
    it. `metrics` stays flat (`dict[str, MetricValue]`) - a value that
    could be `None` is `None`, never a fabricated zero. `details` is the
    one generic escape hatch for structured evidence that doesn't fit a
    flat float dict (a per-class breakdown, a confusion matrix, ...) -
    `None` whenever an evaluator has nothing beyond its flat metrics to
    report."""
    sample_count: int
    matched_samples: int
    unmatched_predictions: int
    unmatched_ground_truth: int
    metrics: dict[str, MetricValue]
    details: dict[str, Any] | None = None


class EvaluatorPlugin(Protocol):
    """The contract every evaluator (built-in or external) implements.
    `evaluator_type` is the exact string a caller passes to `/evaluate`'s
    own `evaluator_type` field and the exact string recorded on the
    resulting `EvaluationResult.evaluator_type` - never a display name,
    never inferred. `format_version` is this evaluator's own result-shape
    version, independent per evaluator type.

    `evaluate` takes an already-computed `MatchResult` (frame-level
    timestamp association - never re-derived here) plus whatever
    evaluator-specific configuration the caller supplied - never a raw
    ground-truth/prediction list, and never persistence/FastAPI/ROS
    access."""
    evaluator_type: str
    format_version: str

    def descriptor(self) -> PluginDescriptor: ...
    def evaluate(self, match_result: MatchResult, parameters: dict[str, Any]) -> EvaluatorOutput: ...


# Backward-compatible alias - every pre-v0.9 backend call site imports this
# name, not EvaluatorPlugin.
Evaluator = EvaluatorPlugin


@dataclass(frozen=True)
class MetricDescriptor:
    """Purely descriptive metadata about a metric an evaluator produces -
    UI hints only. Never consulted by the requirement/acceptance engine,
    which keeps reading `EvaluationResult.metrics[criterion.metric]` by
    string key exactly as it always has - a plugin evaluator produces
    evidence, the profile determines sufficiency, never the reverse."""
    id: str
    type: Literal['float'] = 'float'
    higher_is_better: bool | None = None   # None = no defined direction (e.g. bias)
    unit: str | None = None
