"""`Evaluator`/`EvaluatorOutput` shapes (v0.8, Phase 78), split out of
`evaluators.py` in Phase 82.

**v0.9 (Phase 93) note**: both names are no longer defined here - they're
re-exported from `multisens_sdk.evaluators` (as `EvaluatorPlugin`/
`EvaluatorOutput`; `Evaluator` is kept as the SDK's own backward-compatible
alias for `EvaluatorPlugin`), which now owns them, so an external evaluator
plugin can implement this contract without importing anything
backend-internal. `evaluators.py` still re-exports both names from here, so
`from app.domain.evaluators import EvaluatorOutput` (every existing call
site) is unaffected.
"""
from __future__ import annotations

from multisens_sdk.evaluators import Evaluator, EvaluatorOutput, MetricDescriptor

__all__ = ['Evaluator', 'EvaluatorOutput', 'MetricDescriptor']
