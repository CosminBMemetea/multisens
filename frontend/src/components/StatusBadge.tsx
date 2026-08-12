import type { RequirementStatus } from "../types";

const STATUS_STYLES: Record<RequirementStatus, string> = {
  pass: "bg-emerald-500/15 text-emerald-400 border-emerald-500/30",
  fail: "bg-red-500/15 text-red-400 border-red-500/30",
  na: "bg-slate-500/15 text-slate-400 border-slate-500/30",
};

const STATUS_LABELS: Record<RequirementStatus, string> = {
  pass: "PASS",
  fail: "FAIL",
  na: "N/A",
};

// A requirement's PASS/FAIL/N/A - never a compliance/certification claim,
// see coverage.py's module docstring. Shares ComparisonValidityBadge's
// three-state visual pattern (same emerald/red/slate color language) but
// distinct semantics: this judges one requirement's acceptance criteria
// against selected evidence, not a comparison's evidence quality. Sized
// for a dense matrix cell rather than a standalone badge.
export function StatusBadge({ status, reasons }: { status: RequirementStatus; reasons?: string[] }) {
  return (
    <span
      title={reasons && reasons.length > 0 ? reasons.join("; ") : undefined}
      className={`inline-flex items-center justify-center rounded border px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide ${STATUS_STYLES[status]}`}
    >
      {STATUS_LABELS[status]}
    </span>
  );
}
