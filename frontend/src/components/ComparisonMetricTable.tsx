import {
  formatCoverage,
  formatDelta,
  formatDeltaPp,
  formatMetric,
  formatRelativeDelta,
  labelForMetric,
} from "../format";
import type { ComparisonSide } from "../types";

// Renders whatever metric keys `side.metric_deltas` actually has, sorted
// for a stable order - never a hardcoded classification-only column set
// (v0.8, Phase 86). A comparison's underlying evaluator_type isn't
// exposed on PairwiseComparison itself (deliberately - the metric keys
// already say everything this table needs), so this works identically
// for classification, object_detection, regression, or any future
// evaluator type with zero changes here. `labelForMetric` (format.ts)
// covers every known metric name across every evaluator; anything else
// falls back to the raw key, the same "never a broken page for an
// unrecognized name" posture EvaluationPanel's own generic column
// fallback has.

// Shared by the Sensor Addition (Phase 25) and Ablation (Phase 26) cards -
// both need the identical Metric/Baseline/Candidate/Absolute Δ/Relative Δ
// breakdown, just for a different relationship type. Coverage gets its own
// row with only an absolute (percentage-point) delta, never a relative
// delta - a relative-percentage-of-a-percentage is exactly the confusion
// formatDeltaPp's own docstring warns about.
export function ComparisonMetricTable({ side }: { side: ComparisonSide }) {
  const metricKeys = Object.keys(side.metric_deltas).sort();
  return (
    <table className="w-full text-left text-sm">
      <thead className="border-b border-slate-800 text-xs uppercase tracking-wide text-slate-500">
        <tr>
          <th className="py-1.5 pr-3 font-medium">Metric</th>
          <th className="py-1.5 pr-3 font-medium">Baseline</th>
          <th className="py-1.5 pr-3 font-medium">Candidate</th>
          <th className="py-1.5 pr-3 font-medium">Absolute Δ</th>
          <th className="py-1.5 font-medium">Relative Δ</th>
        </tr>
      </thead>
      <tbody className="font-mono-data">
        {metricKeys.length === 0 ? (
          <tr>
            <td colSpan={5} className="py-1.5 font-sans text-slate-500">
              No metrics available for this comparison.
            </td>
          </tr>
        ) : (
          metricKeys.map((key) => {
            const delta = side.metric_deltas[key];
            return (
              <tr key={key} className="border-b border-slate-800/60 last:border-0">
                <td className="py-1.5 pr-3 font-sans text-slate-400">{labelForMetric(key)}</td>
                <td className="py-1.5 pr-3 text-slate-300">{formatMetric(delta?.baseline ?? null)}</td>
                <td className="py-1.5 pr-3 text-slate-100">{formatMetric(delta?.candidate ?? null)}</td>
                <td className="py-1.5 pr-3 text-slate-100">{formatDelta(delta?.absolute ?? null)}</td>
                <td className="py-1.5 text-slate-100">{formatRelativeDelta(delta?.relative ?? null)}</td>
              </tr>
            );
          })
        )}
        <tr>
          <td className="py-1.5 pr-3 font-sans text-slate-400">Coverage</td>
          <td className="py-1.5 pr-3 text-slate-300">
            {formatCoverage(side.baseline.matched_samples, side.baseline.sample_count)}
          </td>
          <td className="py-1.5 pr-3 text-slate-100">
            {formatCoverage(side.candidate.matched_samples, side.candidate.sample_count)}
          </td>
          <td className="py-1.5 pr-3 text-slate-100" colSpan={2}>
            {formatDeltaPp(side.coverage_delta_pp)}
          </td>
        </tr>
      </tbody>
    </table>
  );
}
