import type { ComparisonValidity, Level, SessionStatus } from "../types";

const LEVEL_STYLES: Record<Level, string> = {
  ok: "bg-emerald-500/15 text-emerald-400 border-emerald-500/30",
  warn: "bg-amber-500/15 text-amber-400 border-amber-500/30",
  error: "bg-red-500/15 text-red-400 border-red-500/30",
  stale: "bg-amber-500/15 text-amber-400 border-amber-500/30",
  unknown: "bg-slate-500/15 text-slate-400 border-slate-500/30",
};

export function LevelBadge({ level, text }: { level: Level; text: string }) {
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded border px-2 py-0.5 text-xs font-medium uppercase tracking-wide ${LEVEL_STYLES[level]}`}
    >
      <span className="h-1.5 w-1.5 rounded-full bg-current" />
      {text}
    </span>
  );
}

export function SourceTypeBadge({ sourceType }: { sourceType: "physical" | "simulated" }) {
  const styles =
    sourceType === "physical"
      ? "bg-emerald-500/15 text-emerald-400 border-emerald-500/30"
      : "bg-cyan-500/15 text-cyan-400 border-cyan-500/30";
  return (
    <span className={`rounded border px-2 py-0.5 text-xs font-semibold uppercase tracking-wide ${styles}`}>
      {sourceType}
    </span>
  );
}

const SESSION_STATUS_STYLES: Record<SessionStatus, string> = {
  created: "bg-slate-500/15 text-slate-400 border-slate-500/30",
  running: "bg-cyan-500/15 text-cyan-400 border-cyan-500/30",
  completed: "bg-emerald-500/15 text-emerald-400 border-emerald-500/30",
  failed: "bg-red-500/15 text-red-400 border-red-500/30",
};

export function SessionStatusBadge({ status }: { status: SessionStatus }) {
  return (
    <span
      className={`rounded border px-2 py-0.5 text-xs font-semibold uppercase tracking-wide ${SESSION_STATUS_STYLES[status]}`}
    >
      {status}
    </span>
  );
}

const VALIDITY_STYLES: Record<ComparisonValidity["status"], string> = {
  valid: "bg-emerald-500/15 text-emerald-400 border-emerald-500/30",
  valid_with_warnings: "bg-amber-500/15 text-amber-400 border-amber-500/30",
  invalid: "bg-red-500/15 text-red-400 border-red-500/30",
};

const VALIDITY_LABELS: Record<ComparisonValidity["status"], string> = {
  valid: "VALID",
  valid_with_warnings: "WARNING",
  invalid: "INVALID",
};

// Evidence-quality indicator only - never a compliance/requirement
// verdict. See ComparisonValidity's docstring in backend/app/domain/
// models.py for why that distinction matters.
export function ComparisonValidityBadge({ validity }: { validity: ComparisonValidity }) {
  return (
    <span
      title={validity.reasons.length > 0 ? validity.reasons.join("; ") : undefined}
      className={`inline-flex items-center gap-1.5 rounded border px-2 py-0.5 text-xs font-semibold uppercase tracking-wide ${VALIDITY_STYLES[validity.status]}`}
    >
      <span className="h-1.5 w-1.5 rounded-full bg-current" />
      {VALIDITY_LABELS[validity.status]}
    </span>
  );
}
