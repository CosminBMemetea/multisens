import type { PolicyStatus } from "../types";

const POLICY_STATUS_STYLES: Record<PolicyStatus, string> = {
  sufficient: "bg-emerald-500/15 text-emerald-400 border-emerald-500/30",
  insufficient: "bg-red-500/15 text-red-400 border-red-500/30",
  undetermined: "bg-amber-500/15 text-amber-400 border-amber-500/30",
};

const POLICY_STATUS_LABELS: Record<PolicyStatus, string> = {
  sufficient: "SUFFICIENT",
  insufficient: "INSUFFICIENT",
  undetermined: "UNDETERMINED",
};

// A whole configuration's standing against one DecisionPolicy - never a
// compliance/certification claim, and a different judgment than
// StatusBadge's per-requirement PASS/FAIL/N/A. UNDETERMINED is amber,
// not slate like StatusBadge's N/A - it means "the real answer depends
// on evidence that doesn't exist yet" (see docs/decision-support.md),
// materially different from "this one requirement has no evidence."
// `null` (NO EVIDENCE) is its own state, not folded into undetermined -
// this configuration_id was named but never evaluated at all.
export function PolicyStatusBadge({ status }: { status: PolicyStatus | null }) {
  if (status === null) {
    return (
      <span className="inline-flex items-center justify-center rounded border border-slate-700 bg-slate-950 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-slate-500">
        No evidence
      </span>
    );
  }
  return (
    <span
      className={`inline-flex items-center justify-center rounded border px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide ${POLICY_STATUS_STYLES[status]}`}
    >
      {POLICY_STATUS_LABELS[status]}
    </span>
  );
}
