import type { QualificationStatus } from "../types";

const STYLES: Record<QualificationStatus, string> = {
  qualifies: "bg-emerald-500/15 text-emerald-400 border-emerald-500/30",
  does_not_qualify: "bg-red-500/15 text-red-400 border-red-500/30",
  undetermined: "bg-amber-500/15 text-amber-400 border-amber-500/30",
};

const LABELS: Record<QualificationStatus, string> = {
  qualifies: "QUALIFIES",
  does_not_qualify: "DOES NOT QUALIFY",
  undetermined: "UNDETERMINED",
};

// The v0.7 counterpart to PolicyStatusBadge - a resource-constraint
// verdict, never conflated with policy_status (a different question:
// "does this configuration's evidence satisfy the requirement policy"
// vs. "does this configuration's resource cost satisfy the resource
// constraints"). UNDETERMINED covers both zero constraints and any
// N/A constraint - never rendered as qualifying either way.
export function QualificationBadge({ status }: { status: QualificationStatus }) {
  return (
    <span
      className={`inline-flex items-center justify-center rounded border px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide ${STYLES[status]}`}
    >
      {LABELS[status]}
    </span>
  );
}
