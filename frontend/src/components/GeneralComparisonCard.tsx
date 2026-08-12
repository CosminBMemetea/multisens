import { ComparisonValidityBadge } from "./Badge";
import { ComparisonMetricTable } from "./ComparisonMetricTable";
import type { PairwiseComparison } from "../types";

// One card per general comparison (relationship === 'general' - anything
// that isn't a single-sensor addition or removal: sensor swaps, multi-
// sensor jumps). Deliberately never attributes the delta to any one
// sensor, since more than one sensor differs between the two sides -
// that attribution is exactly what SensorAdditionCard/AblationCard are
// allowed to imply and this card is not.
export function GeneralComparisonCard({ comparison }: { comparison: PairwiseComparison }) {
  return (
    <div className="flex flex-col gap-3 rounded border border-slate-800 bg-slate-900/40 p-4">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold text-slate-200">
          <span className="font-mono-data">{comparison.candidate_configuration_id}</span> vs{" "}
          <span className="font-mono-data">{comparison.baseline_configuration_id}</span>
        </h3>
        <ComparisonValidityBadge validity={comparison.validity} />
      </div>

      {(comparison.added_sensors.length > 0 || comparison.removed_sensors.length > 0) && (
        <div className="text-xs text-slate-500">
          {comparison.added_sensors.length > 0 && <span>+{comparison.added_sensors.join(", +")} </span>}
          {comparison.removed_sensors.length > 0 && <span>-{comparison.removed_sensors.join(", -")}</span>}
        </div>
      )}

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
