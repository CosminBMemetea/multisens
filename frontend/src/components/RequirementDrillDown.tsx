import { useEffect } from "react";
import { StatusBadge } from "./StatusBadge";
import { formatFractionPercent, formatMetric } from "../format";
import type { Requirement, RequirementResult } from "../types";

interface RequirementDrillDownProps {
  requirement: Requirement;
  result: RequirementResult;
  onClose: () => void;
}

// Sourced entirely from fields already present on RequirementResult - no
// new backend endpoint. Every PASS/FAIL/N/A cell in the matrix must be
// traceable to its underlying evidence (or, for N/A, to a concrete
// reason it has none) - this is the one place that traceability is
// surfaced, so it must never show a status without also showing why.
export function RequirementDrillDown({ requirement, result, onClose }: RequirementDrillDownProps) {
  useEffect(() => {
    function handleKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [onClose]);

  const conditionEntries = Object.entries(requirement.conditions);

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4"
      onClick={onClose}
      role="presentation"
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label={`${requirement.name} evidence`}
        className="flex max-h-[85vh] w-full max-w-lg flex-col gap-4 overflow-y-auto rounded-lg border border-slate-700 bg-slate-900 p-5"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-start justify-between gap-3">
          <div>
            <h2 className="text-base font-semibold text-slate-100">{requirement.name}</h2>
            <p className="font-mono-data text-xs text-slate-500">
              {requirement.task} · {result.configuration_id}
            </p>
          </div>
          <div className="flex items-center gap-2">
            <StatusBadge status={result.status} />
            <button
              onClick={onClose}
              aria-label="Close"
              className="text-lg leading-none text-slate-500 hover:text-slate-300"
            >
              ×
            </button>
          </div>
        </div>

        {requirement.description && <p className="text-sm text-slate-400">{requirement.description}</p>}

        <div className="flex flex-col gap-1">
          <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-500">Conditions</h3>
          {conditionEntries.length === 0 ? (
            <span className="text-sm text-slate-600">no conditions</span>
          ) : (
            <div className="flex flex-wrap gap-1">
              {conditionEntries.map(([key, value]) => (
                <span
                  key={key}
                  className="rounded border border-slate-700 bg-slate-950 px-1.5 py-0.5 font-mono-data text-xs text-slate-400"
                >
                  {key}={String(value)}
                </span>
              ))}
            </div>
          )}
        </div>

        {result.reasons.length > 0 && (
          <div className="flex flex-col gap-1">
            <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-500">
              {result.status === "na" ? "Why N/A" : "Why it failed"}
            </h3>
            <ul className="list-inside list-disc rounded border border-amber-500/30 bg-amber-500/10 p-2 text-sm text-amber-300">
              {result.reasons.map((reason) => (
                <li key={reason}>{reason}</li>
              ))}
            </ul>
          </div>
        )}

        <div className="flex flex-col gap-1">
          <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-500">Evidence</h3>
          {result.evidence ? (
            <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 font-mono-data text-xs text-slate-300">
              <dt className="text-slate-600">Session</dt>
              <dd>{result.evidence.session_id}</dd>
              <dt className="text-slate-600">Scenario</dt>
              <dd>{result.evidence.scenario_id}</dd>
              <dt className="text-slate-600">Prediction source</dt>
              <dd>{result.evidence.source_id}</dd>
              <dt className="text-slate-600">Matched samples</dt>
              <dd>
                {result.evidence.matched_samples} / {result.evidence.sample_count}
              </dd>
              <dt className="text-slate-600">Coverage</dt>
              <dd>{formatFractionPercent(result.evidence.coverage)}</dd>
            </dl>
          ) : (
            <span className="text-sm text-slate-600">No evidence was selected.</span>
          )}
        </div>

        <div className="flex flex-col gap-1">
          <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-500">Acceptance criteria</h3>
          {result.criteria.length === 0 ? (
            <span className="text-sm text-slate-600">No criteria were evaluated.</span>
          ) : (
            <table className="w-full text-left text-xs">
              <thead className="text-slate-500">
                <tr>
                  <th className="py-1 pr-2 font-medium">Criterion</th>
                  <th className="py-1 pr-2 font-medium">Observed</th>
                  <th className="py-1 font-medium">Status</th>
                </tr>
              </thead>
              <tbody className="font-mono-data text-slate-300">
                {result.criteria.map((c) => (
                  <tr key={`${c.metric}-${c.operator}-${c.threshold}`} className="border-t border-slate-800/60">
                    <td className="py-1.5 pr-2">
                      {c.metric} {c.operator} {c.threshold}
                    </td>
                    <td className="py-1.5 pr-2">{formatMetric(c.observed)}</td>
                    <td className="py-1.5">
                      <StatusBadge status={c.status} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>
    </div>
  );
}
