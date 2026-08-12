import { formatCoverage, formatDelta, formatDeltaPp, formatMetric, formatRelativeDelta } from "../format";
import type { ComparisonSide } from "../types";

const METRIC_ORDER = ["accuracy", "precision_macro", "recall_macro", "f1_macro"] as const;

const METRIC_LABELS: Record<(typeof METRIC_ORDER)[number], string> = {
  accuracy: "Accuracy",
  precision_macro: "Precision (macro)",
  recall_macro: "Recall (macro)",
  f1_macro: "F1 (macro)",
};

// Shared by the Sensor Addition (Phase 25) and Ablation (Phase 26) cards -
// both need the identical Metric/Baseline/Candidate/Absolute Δ/Relative Δ
// breakdown, just for a different relationship type. Coverage gets its own
// row with only an absolute (percentage-point) delta, never a relative
// delta - a relative-percentage-of-a-percentage is exactly the confusion
// formatDeltaPp's own docstring warns about.
export function ComparisonMetricTable({ side }: { side: ComparisonSide }) {
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
        {METRIC_ORDER.map((key) => {
          const delta = side.metric_deltas[key];
          return (
            <tr key={key} className="border-b border-slate-800/60 last:border-0">
              <td className="py-1.5 pr-3 font-sans text-slate-400">{METRIC_LABELS[key]}</td>
              <td className="py-1.5 pr-3 text-slate-300">{formatMetric(delta?.baseline ?? null)}</td>
              <td className="py-1.5 pr-3 text-slate-100">{formatMetric(delta?.candidate ?? null)}</td>
              <td className="py-1.5 pr-3 text-slate-100">{formatDelta(delta?.absolute ?? null)}</td>
              <td className="py-1.5 text-slate-100">{formatRelativeDelta(delta?.relative ?? null)}</td>
            </tr>
          );
        })}
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
