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

// Comparison deltas (v0.3): a signed value needs its direction visible at
// a glance - "+0.06" and "-0.06" read very differently, unlike a plain
// metric. null is still N/A, never a fabricated "+0.000".
export function formatDelta(value: number | null): string {
  if (value === null) return "N/A";
  if (value === 0) return "0.000";
  return value > 0 ? `+${value.toFixed(3)}` : value.toFixed(3);
}

// Percentage POINTS, never a relative percentage - matches
// ComparisonSide.coverage_delta_pp's own contract (see types.ts). The "pp"
// suffix is deliberate: it's the one thing stopping "-4 pp" from being
// misread as "-4%", a different and easily-confused quantity.
export function formatDeltaPp(value: number | null): string {
  if (value === null) return "N/A";
  if (value === 0) return "0.0 pp";
  return `${value > 0 ? "+" : ""}${value.toFixed(1)} pp`;
}

// MetricDelta.relative (a fraction, e.g. 0.068 for "6.8% relative change"
// vs baseline) - distinct from formatDeltaPp, which is percentage POINTS
// of an already-percent quantity (coverage). This is a relative change of
// an arbitrary metric, always shown with a % sign since it genuinely is
// one - never confuse the two call sites.
export function formatRelativeDelta(value: number | null): string {
  if (value === null) return "N/A";
  if (value === 0) return "0.0%";
  return `${value > 0 ? "+" : ""}${(value * 100).toFixed(1)}%`;
}

// GroupCoverage.requirement_coverage/evidence_completeness (v0.4): both
// are already a fraction (0-1) or null, unlike formatCoverage's raw-count
// inputs - null means "nothing decided yet" (pass+fail, or the total,
// is 0), never a fabricated 0%.
export function formatFractionPercent(value: number | null): string {
  if (value === null) return "N/A";
  return `${Math.round(value * 100)}%`;
}

// ResourceMetricSummary values (v0.7): null means no real evidence for
// this metric in this window - renders as an em dash, never "0", which
// would claim a genuine zero-valued measurement that never happened
// (see app/domain/resources.py's own "unavailable is not zero" rule).
// A real 0.0 (e.g. 0 fps while disconnected) still renders as "0" - the
// two must stay visually distinct at a glance, same discipline as
// formatMetric/formatDelta above.
export function formatResourceValue(value: number | null, unit: string): string {
  if (value === null) return "—";
  const decimals = unit === "%" || unit === "ms" || unit === "fps" ? 0 : 1;
  return `${value.toFixed(decimals)} ${unit}`;
}
