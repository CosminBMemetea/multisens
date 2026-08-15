import type { ComparisonValidity, EvidenceRelationship, Level, SessionStatus } from "../types";

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

// v1.0-RC, issue #124 - Dashboard inference status, kept visually and
// structurally separate from sensor connection health (LevelBadge above):
// a sensor's video can be perfectly healthy with no inference attached at
// all, and vice versa - two independent state machines (#122's own
// PredictionConnectorInstance vs. rtsp_ingestion_node's own connection
// state), never conflated into one badge.
export type InferenceStatus = "ACTIVE" | "NONE" | "ERROR";

const INFERENCE_STATUS_STYLES: Record<InferenceStatus, string> = {
  ACTIVE: "bg-emerald-500/15 text-emerald-400 border-emerald-500/30",
  NONE: "bg-slate-500/15 text-slate-400 border-slate-500/30",
  ERROR: "bg-red-500/15 text-red-400 border-red-500/30",
};

export function InferenceStatusBadge({ status }: { status: InferenceStatus }) {
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded border px-2 py-0.5 text-xs font-medium uppercase tracking-wide ${INFERENCE_STATUS_STYLES[status]}`}
    >
      <span className="h-1.5 w-1.5 rounded-full bg-current" />
      Inference: {status}
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

// v0.9.1, issue #120 - Evidence Playback. TP/TN both "the prediction
// matched ground truth"; FP/FN both "it didn't" - styled by correctness,
// not by which specific letter, so a reader scans for red/green first.
const OUTCOME_STYLES: Record<"TP" | "FP" | "FN" | "TN", string> = {
  TP: "bg-emerald-500/15 text-emerald-400 border-emerald-500/30",
  TN: "bg-emerald-500/15 text-emerald-400 border-emerald-500/30",
  FP: "bg-red-500/15 text-red-400 border-red-500/30",
  FN: "bg-red-500/15 text-red-400 border-red-500/30",
};

export function OutcomeBadge({ outcome }: { outcome: "TP" | "FP" | "FN" | "TN" | null }) {
  if (outcome === null) {
    return <span className="text-xs text-slate-600">—</span>;
  }
  return (
    <span
      className={`rounded border px-1.5 py-0.5 text-[11px] font-semibold uppercase tracking-wide ${OUTCOME_STYLES[outcome]}`}
    >
      {outcome}
    </span>
  );
}

// Fixed, pre-approved copy per relationship value (never a composed
// sentence from raw prediction values) - the whole point is that
// "rear fixed front's error"-style causal language can never leak in
// through a future edit if the wording lives in one place, keyed by the
// server-computed relationship, not assembled from source values.
const RELATIONSHIP_STYLES: Record<EvidenceRelationship, string> = {
  AGREE_POSITIVE: "bg-emerald-500/15 text-emerald-400 border-emerald-500/30",
  AGREE_NEGATIVE: "bg-cyan-500/15 text-cyan-400 border-cyan-500/30",
  DISAGREE: "bg-amber-500/15 text-amber-400 border-amber-500/30",
  ONLY_ONE_SOURCE_AVAILABLE: "bg-slate-500/15 text-slate-400 border-slate-500/30",
  NO_COMMON_GT_SAMPLE: "bg-slate-500/15 text-slate-400 border-slate-500/30",
};

const RELATIONSHIP_LABELS: Record<EvidenceRelationship, string> = {
  AGREE_POSITIVE: "sources agree",
  AGREE_NEGATIVE: "sources agree",
  DISAGREE: "disagreement",
  ONLY_ONE_SOURCE_AVAILABLE: "one source only",
  NO_COMMON_GT_SAMPLE: "no evidence",
};

export function RelationshipBadge({ relationship }: { relationship: EvidenceRelationship }) {
  return (
    <span
      className={`rounded border px-2 py-0.5 text-xs font-medium uppercase tracking-wide ${RELATIONSHIP_STYLES[relationship]}`}
    >
      {RELATIONSHIP_LABELS[relationship]}
    </span>
  );
}
