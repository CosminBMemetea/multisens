// "unavailable" is a real sentinel value the backend sends deliberately
// when a metric genuinely can't be measured (see rtsp_ingestion_node.py /
// sync_status_node.py docstrings) - must render as-is, never have a unit
// suffix appended to it.
export function formatMs(value: string | undefined): string {
  if (value === undefined) return "—";
  if (value === "unavailable") return value;
  return `${value}ms`;
}

// Evaluation metrics (v0.2): a `null` metric means "not calculable" (e.g.
// a class that was never predicted), which the backend deliberately never
// coerces to 0.0 - see backend/app/domain/metrics.py. Rendering it as "0"
// here would silently undo that distinction, so it must render as "N/A".
export function formatMetric(value: number | null): string {
  if (value === null) return "N/A";
  return value.toFixed(3);
}

// A zero-sample denominator means "nothing to measure coverage of" (no
// ground truth for this task/configuration yet), not "0% coverage" - same
// N/A-not-zero rule as formatMetric.
export function formatCoverage(matched: number, total: number): string {
  if (total === 0) return "N/A";
  return `${Math.round((matched / total) * 100)}%`;
}
