import { ComparisonValidityBadge } from "./Badge";
import { ComparisonMetricTable } from "./ComparisonMetricTable";
import type { PairwiseComparison } from "../types";

// One card per direct sensor addition (relationship === 'direct_addition',
// enforced by the caller). Copy stays strictly observational - "added to,"
// never "improves" or "causes" - per the v0.3 non-causal rule.
export function SensorAdditionCard({ comparison }: { comparison: PairwiseComparison }) {
  const addedSensor = comparison.added_sensors[0] ?? "?";
  return (
    <div className="flex flex-col gap-3 rounded border border-slate-800 bg-slate-900/40 p-4">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold text-slate-200">
          <span className="text-cyan-400">{addedSensor}</span> added to{" "}
          <span className="font-mono-data">{comparison.baseline_configuration_id}</span>
        </h3>
        <ComparisonValidityBadge validity={comparison.validity} />
      </div>

      <ComparisonMetricTable side={comparison.reported} />

      <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-slate-500">
        <span>Common samples: {comparison.common_set.common_sample_count ?? "N/A"}</span>
        <span>Tolerance: {comparison.tolerance_ms}ms</span>
        {comparison.validity.reasons.length > 0 && (
          <span className="text-amber-400">{comparison.validity.reasons.join("; ")}</span>
        )}
      </div>
    </div>
  );
}
