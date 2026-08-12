import { ComparisonValidityBadge } from "./Badge";
import { ComparisonMetricTable } from "./ComparisonMetricTable";
import type { PairwiseComparison } from "../types";

// One card per direct sensor removal (relationship === 'direct_removal',
// enforced by the caller) from a full-configuration baseline. Copy stays
// strictly observational - "observed metric penalty when removing X" -
// never "X importance" or "requirement coverage lost", per the
// product-direction clarification on issue #27.
export function AblationCard({ comparison }: { comparison: PairwiseComparison }) {
  const removedSensor = comparison.removed_sensors[0] ?? "?";
  return (
    <div className="flex flex-col gap-3 rounded border border-slate-800 bg-slate-900/40 p-4">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold text-slate-200">
          Observed penalty removing <span className="text-amber-400">{removedSensor}</span> from{" "}
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
