import { useEffect, useMemo, useState } from "react";
import { fetchSessionEvidence, predictionFrameUrl } from "../api";
import { OutcomeBadge, RelationshipBadge } from "./Badge";
import type { EvidenceSample, GroundTruthEvent, SourceEvidence } from "../types";

interface EvidencePlaybackProps {
  sessionId: string;
  tasks: string[];
  groundTruth: GroundTruthEvent[];
}

function rawValueLabel(value: Record<string, unknown> | null): string {
  if (value === null) return "—";
  if (typeof value.label === "string") return value.label;
  return JSON.stringify(value);
}

// Raw epoch ms is unreadable in a table ("1755590000000" tells you
// nothing). Shown instead as elapsed time from the table's own first row
// - self-consistent regardless of which clock produced the timestamps -
// with the full wall-clock time and raw ms kept in the tooltip for
// anyone who needs to cross-reference against logs.
function formatElapsed(timestampMs: number, t0Ms: number): string {
  const deltaS = (timestampMs - t0Ms) / 1000;
  return `t+${deltaS.toFixed(1)}s`;
}

function formatTimestampTitle(timestampMs: number): string {
  return `${new Date(timestampMs).toLocaleTimeString()} (${timestampMs} ms)`;
}

// Evidence Playback needs an explicit "which label is the event of
// interest" choice to classify TP/FP/FN/TN and AGREE_POSITIVE/NEGATIVE -
// the backend refuses to guess (positive_label has no default), so this
// never offers anything the caller didn't type; it only narrows the
// *choices* to labels genuinely observed in this task's own ground
// truth, never an arbitrary free-text guess.
function observedLabels(groundTruth: GroundTruthEvent[], task: string): string[] {
  const labels = new Set<string>();
  for (const g of groundTruth) {
    if (g.task === task && typeof g.value.label === "string") {
      labels.add(g.value.label);
    }
  }
  return [...labels].sort();
}

export function EvidencePlayback({ sessionId, tasks, groundTruth }: EvidencePlaybackProps) {
  const [selectedTask, setSelectedTask] = useState<string>(tasks[0] ?? "");
  const [positiveLabel, setPositiveLabel] = useState<string>("");
  const [evidence, setEvidence] = useState<EvidenceSample[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  // RideSafe bring-up, Phase 24 - "inspect frame" lightbox. Only ever
  // populated from a real EvidenceSample/SourceEvidence pair already in
  // `evidence` state - never a synthesized path.
  const [inspecting, setInspecting] = useState<{ sample: EvidenceSample; src: SourceEvidence } | null>(null);

  useEffect(() => {
    setSelectedTask((current) => (tasks.includes(current) ? current : (tasks[0] ?? "")));
  }, [tasks]);

  const labels = useMemo(() => observedLabels(groundTruth, selectedTask), [groundTruth, selectedTask]);

  useEffect(() => {
    // Deliberately never auto-picks labels[0] as a default - which label
    // counts as "the event of interest" is a modeling decision this
    // component must never guess (same posture the backend's own
    // required, undefaulted positive_label parameter already has - see
    // domain/evidence_playback.py's module docstring). Only preserves the
    // current choice if it's still a valid label for the newly selected
    // task; otherwise the picker goes back to unselected.
    setPositiveLabel((current) => (labels.includes(current) ? current : ""));
  }, [labels]);

  useEffect(() => {
    if (!selectedTask || !positiveLabel) {
      setEvidence(null);
      return;
    }
    let cancelled = false;
    fetchSessionEvidence(sessionId, { task: selectedTask, positive_label: positiveLabel })
      .then((fetched) => {
        if (!cancelled) {
          setEvidence(fetched);
          setError(null);
        }
      })
      .catch((err) => {
        if (!cancelled) setError(String(err));
      });
    return () => {
      cancelled = true;
    };
  }, [sessionId, selectedTask, positiveLabel]);

  if (tasks.length === 0) {
    return (
      <section className="rounded border border-slate-800 bg-slate-900/40 p-4">
        <h2 className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">Evidence Playback</h2>
        <span className="text-slate-500">No ground truth ingested yet - nothing to inspect.</span>
      </section>
    );
  }

  // Every sample carries the same set of (configuration_id, source_id)
  // columns (the backend guarantees this - one column per source known
  // anywhere in the session, present even when that source has no match
  // for a given sample) - so the first sample's own source list is the
  // canonical column set for the whole table.
  const columns = evidence?.[0]?.sources.map((s) => ({
    configuration_id: s.configuration_id,
    source_id: s.source_id,
  })) ?? [];

  const t0Ms = evidence && evidence.length > 0
    ? Math.min(...evidence.map((s) => s.gt_timestamp_ms))
    : 0;

  return (
    <section className="flex flex-col gap-4 rounded border border-slate-800 bg-slate-900/40 p-4">
      <div className="flex items-center justify-between">
        <h2 className="text-xs font-semibold uppercase tracking-wide text-slate-500">Evidence Playback</h2>
        <div className="flex items-center gap-2">
          {tasks.length > 1 && (
            <select
              value={selectedTask}
              onChange={(e) => setSelectedTask(e.target.value)}
              className="rounded border border-slate-700 bg-slate-950 px-2 py-1 text-xs text-slate-200"
            >
              {tasks.map((t) => (
                <option key={t} value={t}>
                  {t}
                </option>
              ))}
            </select>
          )}
          {labels.length > 0 && (
            <label className="flex items-center gap-1.5 text-xs text-slate-500">
              positive label
              <select
                value={positiveLabel}
                onChange={(e) => setPositiveLabel(e.target.value)}
                className="rounded border border-slate-700 bg-slate-950 px-2 py-1 text-xs text-slate-200"
              >
                {/* No option is selected by default (value="") - which
                    label counts as "positive" is never guessed. */}
                <option value="" disabled>
                  Select…
                </option>
                {labels.map((l) => (
                  <option key={l} value={l}>
                    {l}
                  </option>
                ))}
              </select>
            </label>
          )}
        </div>
      </div>

      {error && <div className="text-sm text-red-400">{error}</div>}

      {labels.length === 0 ? (
        <span className="text-slate-500">
          Ground truth for &apos;{selectedTask}&apos; isn&apos;t label-shaped - Evidence Playback's per-sample
          outcome/agreement classification only applies to classification-style tasks.
        </span>
      ) : positiveLabel === "" ? (
        <span className="text-slate-500">
          Choose which label is the event of interest (&quot;positive label&quot; above) to compute per-sample
          outcomes - never assumed automatically.
        </span>
      ) : evidence === null ? (
        <span className="text-slate-500">Loading…</span>
      ) : evidence.length === 0 ? (
        <span className="text-slate-500">No ground truth samples for &apos;{selectedTask}&apos;.</span>
      ) : (
        <div className="overflow-x-auto rounded border border-slate-800">
          <table className="w-full text-left text-sm">
            <thead className="border-b border-slate-800 bg-slate-950/60 text-xs uppercase tracking-wide text-slate-500">
              <tr>
                <th className="px-3 py-2 font-medium">t</th>
                <th className="px-3 py-2 font-medium">GT</th>
                {columns.map((c) => (
                  <th key={`${c.configuration_id}::${c.source_id}`} className="px-3 py-2 font-medium">
                    <div className="font-mono-data normal-case text-slate-300">{c.configuration_id}</div>
                    <div className="font-mono-data text-[10px] normal-case text-slate-600">{c.source_id}</div>
                  </th>
                ))}
                <th className="px-3 py-2 font-medium">Relationship</th>
              </tr>
            </thead>
            <tbody>
              {evidence.map((sample) => (
                <tr key={sample.gt_sample_id} className="border-b border-slate-800/60 last:border-0">
                  <td
                    className="px-3 py-2 font-mono-data text-slate-400"
                    title={formatTimestampTitle(sample.gt_timestamp_ms)}
                  >
                    {formatElapsed(sample.gt_timestamp_ms, t0Ms)}
                  </td>
                  <td className="px-3 py-2 font-mono-data text-slate-200">{rawValueLabel(sample.gt_value)}</td>
                  {columns.map((c) => {
                    const src = sample.sources.find(
                      (s) => s.configuration_id === c.configuration_id && s.source_id === c.source_id,
                    );
                    if (!src || src.prediction_id === null) {
                      return (
                        <td
                          key={`${c.configuration_id}::${c.source_id}`}
                          className="px-3 py-2 font-mono-data text-xs text-slate-600"
                        >
                          NO COMMON EVIDENCE
                        </td>
                      );
                    }
                    return (
                      <td key={`${c.configuration_id}::${c.source_id}`} className="px-3 py-2">
                        <div className="flex items-center gap-2">
                          <span className="font-mono-data text-slate-200">{rawValueLabel(src.value)}</span>
                          <OutcomeBadge outcome={src.outcome} />
                        </div>
                        <div className="mt-0.5 flex items-center gap-2 text-[10px] text-slate-600">
                          {src.confidence !== null && <span>conf {src.confidence.toFixed(2)}</span>}
                          {src.match_delta_ms !== null && <span>Δt {src.match_delta_ms}ms</span>}
                          {typeof src.metadata.snapshot_path === "string" && (
                            <button
                              type="button"
                              onClick={() => setInspecting({ sample, src })}
                              className="rounded border border-slate-700 px-1.5 py-0.5 text-slate-400 hover:border-slate-500 hover:text-slate-200"
                            >
                              inspect frame
                            </button>
                          )}
                        </div>
                      </td>
                    );
                  })}
                  <td className="px-3 py-2">
                    <RelationshipBadge relationship={sample.relationship} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {inspecting && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 p-6"
          onClick={() => setInspecting(null)}
        >
          <div
            className="flex max-h-full max-w-3xl flex-col gap-3 overflow-auto rounded border border-slate-700 bg-slate-950 p-4"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-start justify-between gap-4">
              <div className="font-mono-data text-xs text-slate-400">
                <div className="text-slate-200">{inspecting.src.source_id}</div>
                <div title={formatTimestampTitle(inspecting.sample.gt_timestamp_ms)}>
                  {formatElapsed(inspecting.sample.gt_timestamp_ms, t0Ms)}
                </div>
              </div>
              <button
                type="button"
                onClick={() => setInspecting(null)}
                className="rounded border border-slate-700 px-2 py-1 text-xs text-slate-400 hover:border-slate-500 hover:text-slate-200"
              >
                close
              </button>
            </div>
            <img
              src={predictionFrameUrl(sessionId, inspecting.src.prediction_id!)}
              alt={`${inspecting.src.source_id} frame at t=${inspecting.sample.gt_timestamp_ms}ms`}
              className="max-h-[70vh] rounded border border-slate-800 object-contain"
            />
            <dl className="grid grid-cols-2 gap-x-4 gap-y-1 font-mono-data text-xs text-slate-400">
              <div className="flex justify-between">
                <dt>GT</dt>
                <dd className="text-slate-200">{rawValueLabel(inspecting.sample.gt_value)}</dd>
              </div>
              <div className="flex justify-between">
                <dt>prediction</dt>
                <dd className="text-slate-200">{rawValueLabel(inspecting.src.value)}</dd>
              </div>
              <div className="flex justify-between">
                <dt>confidence</dt>
                <dd className="text-slate-200">{inspecting.src.confidence?.toFixed(2) ?? "—"}</dd>
              </div>
              <div className="flex justify-between">
                <dt>outcome</dt>
                <dd>
                  <OutcomeBadge outcome={inspecting.src.outcome} />
                </dd>
              </div>
            </dl>
          </div>
        </div>
      )}
    </section>
  );
}
