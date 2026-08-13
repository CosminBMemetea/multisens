import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { fetchSessionEvaluation, fetchSessionTimeline, runEvaluation } from "../api";
import { summaryColumnsFor } from "../evaluationColumns";
import { formatCoverage, formatMetric } from "../format";
import {
  isClassificationResult,
  isDetectionResult,
  isRegressionResult,
  type DetectionEvaluationResult,
  type EvaluationResult,
  type RegressionEvaluationResult,
  type TimelineEvent,
} from "../types";

const TIMELINE_STYLES: Record<TimelineEvent["kind"], string> = {
  correct: "bg-emerald-400",
  incorrect: "bg-red-400",
  missing_prediction: "bg-amber-400",
  unmatched_prediction: "bg-slate-500",
};

const TIMELINE_LABELS: Record<TimelineEvent["kind"], string> = {
  correct: "Correct",
  incorrect: "Incorrect",
  missing_prediction: "Missing prediction",
  unmatched_prediction: "Unmatched prediction",
};

const TIMELINE_KINDS = Object.keys(TIMELINE_LABELS) as TimelineEvent["kind"][];

function ConfusionMatrixView({ result }: { result: EvaluationResult }) {
  if (!result.confusion_matrix || result.confusion_matrix.labels.length === 0) {
    return <span className="text-sm text-slate-500">No confusion matrix available.</span>;
  }
  const { labels, counts } = result.confusion_matrix;
  return (
    <div>
      <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">
        Confusion matrix · {result.configuration_id}
      </h3>
      <div className="overflow-x-auto">
        <table className="border-collapse text-sm">
          <thead>
            <tr>
              <th className="p-2 text-right text-[10px] uppercase text-slate-600">actual \ predicted</th>
              {labels.map((label) => (
                <th key={label} className="border border-slate-800 p-2 font-mono-data text-xs text-slate-400">
                  {label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {labels.map((rowLabel, i) => (
              <tr key={rowLabel}>
                <th className="border border-slate-800 p-2 text-right font-mono-data text-xs text-slate-400">
                  {rowLabel}
                </th>
                {counts[i].map((count, j) => (
                  <td
                    key={labels[j]}
                    className={`border border-slate-800 p-2 text-center font-mono-data ${
                      i === j ? "bg-emerald-500/10 text-emerald-300" : "text-slate-300"
                    }`}
                  >
                    {count}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// Per-class precision/recall/F1 breakdown - genuinely additional detail
// beyond the summary row's own overall numbers, the same role the
// confusion matrix plays for classification. Never a confusion matrix
// forced onto detection - a fundamentally different question (which
// classes get confused for which) that object-level TP/FP/FN doesn't
// answer at all.
function DetectionPerClassView({ result }: { result: DetectionEvaluationResult }) {
  const perClass = result.details?.per_class;
  const labels = perClass ? Object.keys(perClass).sort() : [];
  if (labels.length === 0) {
    return <span className="text-sm text-slate-500">No per-class breakdown available.</span>;
  }
  return (
    <div>
      <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">
        Per-class · {result.configuration_id}
      </h3>
      <div className="overflow-x-auto rounded border border-slate-800">
        <table className="w-full text-left text-sm">
          <thead className="border-b border-slate-800 bg-slate-950/60 text-xs uppercase tracking-wide text-slate-500">
            <tr>
              <th className="px-3 py-1.5 font-medium">Class</th>
              <th className="px-3 py-1.5 font-medium">TP</th>
              <th className="px-3 py-1.5 font-medium">FP</th>
              <th className="px-3 py-1.5 font-medium">FN</th>
              <th className="px-3 py-1.5 font-medium">Precision</th>
              <th className="px-3 py-1.5 font-medium">Recall</th>
              <th className="px-3 py-1.5 font-medium">F1</th>
            </tr>
          </thead>
          <tbody className="font-mono-data">
            {labels.map((label) => {
              const m = perClass![label];
              return (
                <tr key={label} className="border-b border-slate-800/60 last:border-0">
                  <td className="px-3 py-1.5 font-sans text-slate-300">{label}</td>
                  <td className="px-3 py-1.5 text-slate-200">{m.true_positives}</td>
                  <td className="px-3 py-1.5 text-slate-200">{m.false_positives}</td>
                  <td className="px-3 py-1.5 text-slate-200">{m.false_negatives}</td>
                  <td className="px-3 py-1.5 text-slate-200">{formatMetric(m.precision)}</td>
                  <td className="px-3 py-1.5 text-slate-200">{formatMetric(m.recall)}</td>
                  <td className="px-3 py-1.5 text-slate-200">{formatMetric(m.f1)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function RegressionUnitNote({ result }: { result: RegressionEvaluationResult }) {
  const unit = result.details?.unit;
  if (!unit) return null;
  return (
    <span className="text-xs text-slate-500">
      Values reported in <span className="font-mono-data text-slate-400">{unit}</span>.
    </span>
  );
}

function Timeline({ events }: { events: TimelineEvent[] | null }) {
  if (events === null) {
    return <span className="text-sm text-slate-500">Loading timeline…</span>;
  }
  if (events.length === 0) {
    return <span className="text-sm text-slate-500">No timeline events.</span>;
  }
  return (
    <div>
      <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">Timeline</h3>
      <div className="flex flex-wrap gap-1">
        {events.map((e, i) => (
          <span
            key={i}
            title={[
              `${TIMELINE_LABELS[e.kind]} @ ${e.timestamp_ms}ms`,
              e.ground_truth_label ? `actual: ${e.ground_truth_label}` : null,
              e.predicted_label ? `predicted: ${e.predicted_label}` : null,
            ]
              .filter(Boolean)
              .join(" · ")}
            className={`h-4 w-4 rounded-sm ${TIMELINE_STYLES[e.kind]}`}
          />
        ))}
      </div>
      <div className="mt-2 flex flex-wrap gap-3 text-xs text-slate-500">
        {TIMELINE_KINDS.map((kind) => (
          <span key={kind} className="flex items-center gap-1.5">
            <span className={`h-2.5 w-2.5 rounded-sm ${TIMELINE_STYLES[kind]}`} />
            {TIMELINE_LABELS[kind]}
          </span>
        ))}
      </div>
    </div>
  );
}

interface EvaluationPanelProps {
  sessionId: string;
  tasks: string[];
}

export function EvaluationPanel({ sessionId, tasks }: EvaluationPanelProps) {
  const [results, setResults] = useState<EvaluationResult[] | null>(null);
  const [selectedTask, setSelectedTask] = useState<string>(tasks[0] ?? "");
  const [selectedConfig, setSelectedConfig] = useState<string | null>(null);
  const [timeline, setTimeline] = useState<TimelineEvent[] | null>(null);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function loadResults() {
    try {
      const fetched = await fetchSessionEvaluation(sessionId);
      setResults(fetched);
      setError(null);
      setSelectedConfig((current) => {
        const forTask = fetched.filter((r) => r.task === selectedTask);
        if (forTask.some((r) => r.configuration_id === current)) return current;
        return forTask[0]?.configuration_id ?? null;
      });
    } catch (err) {
      setError(String(err));
    }
  }

  useEffect(() => {
    // `tasks` arrives asynchronously (SessionDetail fetches ground truth
    // after this component has already mounted with tasks=[]), so the
    // initial useState(tasks[0] ?? "") never sees the real value - keep
    // selectedTask in sync as `tasks` changes, preserving the user's
    // current pick if it's still valid.
    setSelectedTask((current) => (tasks.includes(current) ? current : (tasks[0] ?? "")));
  }, [tasks]);

  useEffect(() => {
    loadResults();
    // Reload whenever the session or selected task changes - not on every
    // render, and not keyed on `results` itself (that would loop).
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId, selectedTask]);

  const taskResults = (results ?? []).filter((r) => r.task === selectedTask);
  const selectedResult = taskResults.find((r) => r.configuration_id === selectedConfig) ?? null;
  // /timeline is classification-only (v0.8, Phase 84 - a documented scope
  // boundary, not an oversight); fetching it for any other evaluator_type
  // would just 422. Skip the request entirely rather than surface that as
  // a generic page-level error.
  const timelineEligible = selectedResult !== null && isClassificationResult(selectedResult);

  useEffect(() => {
    if (!selectedConfig || !selectedTask || !timelineEligible) {
      setTimeline(null);
      return;
    }
    let cancelled = false;
    setTimeline(null);
    fetchSessionTimeline(sessionId, { task: selectedTask, configuration_id: selectedConfig })
      .then((events) => {
        if (!cancelled) setTimeline(events);
      })
      .catch((err) => {
        if (!cancelled) setError(String(err));
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId, selectedConfig, selectedTask, timelineEligible]);

  async function handleRunEvaluation() {
    setRunning(true);
    setError(null);
    try {
      await runEvaluation(sessionId, { task: selectedTask });
      await loadResults();
    } catch (err) {
      setError(String(err));
    } finally {
      setRunning(false);
    }
  }

  if (tasks.length === 0) {
    return (
      <section className="rounded border border-slate-800 bg-slate-900/40 p-4">
        <h2 className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">Evaluation</h2>
        <span className="text-slate-500">No ground truth ingested yet - nothing to evaluate.</span>
      </section>
    );
  }

  const columns = summaryColumnsFor(taskResults);

  return (
    <section className="flex flex-col gap-4 rounded border border-slate-800 bg-slate-900/40 p-4">
      <div className="flex items-center justify-between">
        <h2 className="text-xs font-semibold uppercase tracking-wide text-slate-500">Evaluation</h2>
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
          <button
            onClick={handleRunEvaluation}
            disabled={running}
            className="rounded border border-cyan-500/40 bg-cyan-500/10 px-3 py-1 text-xs font-medium text-cyan-400 hover:bg-cyan-500/20 disabled:opacity-50"
          >
            {running ? "Running…" : "Run Evaluation"}
          </button>
          {taskResults.length >= 2 && (
            <Link
              to={`/comparison?session=${sessionId}&task=${encodeURIComponent(selectedTask)}`}
              className="rounded border border-slate-700 px-3 py-1 text-xs font-medium text-slate-300 hover:border-cyan-500/40 hover:text-cyan-400"
            >
              Compare configurations →
            </Link>
          )}
        </div>
      </div>

      {error && <div className="text-sm text-red-400">{error}</div>}

      {taskResults.length === 0 ? (
        <span className="text-slate-500">Not evaluated yet for task &apos;{selectedTask}&apos;.</span>
      ) : (
        <>
          <div className="overflow-x-auto rounded border border-slate-800">
            <table className="w-full text-left text-sm">
              <thead className="border-b border-slate-800 bg-slate-950/60 text-xs uppercase tracking-wide text-slate-500">
                <tr>
                  <th className="px-3 py-2 font-medium">Configuration</th>
                  <th className="px-3 py-2 font-medium">Coverage</th>
                  {columns.map((col) => (
                    <th key={col.key} className="px-3 py-2 font-medium">
                      {col.label}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {taskResults.map((r) => (
                  <tr
                    key={r.configuration_id}
                    onClick={() => setSelectedConfig(r.configuration_id)}
                    className={`cursor-pointer border-b border-slate-800/60 last:border-0 hover:bg-slate-900/60 ${
                      r.configuration_id === selectedConfig ? "bg-slate-900/80" : ""
                    }`}
                  >
                    <td className="px-3 py-2 font-mono-data text-slate-200">{r.configuration_id}</td>
                    <td className="px-3 py-2 font-mono-data text-slate-400">
                      {formatCoverage(r.matched_samples, r.sample_count)}
                      <span className="ml-1 text-slate-600">
                        ({r.matched_samples}/{r.sample_count})
                      </span>
                    </td>
                    {columns.map((col) => (
                      <td key={col.key} className="px-3 py-2 font-mono-data text-slate-200">
                        {formatMetric(r.metrics[col.key] ?? null)}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {selectedResult && isClassificationResult(selectedResult) && (
            <ConfusionMatrixView result={selectedResult} />
          )}
          {selectedResult && isDetectionResult(selectedResult) && (
            <DetectionPerClassView result={selectedResult} />
          )}
          {selectedResult && isRegressionResult(selectedResult) && (
            <RegressionUnitNote result={selectedResult} />
          )}
          {selectedResult &&
            !isClassificationResult(selectedResult) &&
            !isDetectionResult(selectedResult) &&
            !isRegressionResult(selectedResult) && (
              // An evaluator_type this frontend build doesn't recognize yet
              // (master prompt §78) - the summary table above already
              // rendered its raw metrics generically; this is just an
              // honest note that there's no dedicated detail panel for it,
              // never a broken page.
              <span className="text-sm text-slate-500">
                No evaluator-specific visualization available for evaluator_type &apos;
                {selectedResult.evaluator_type}&apos;.
              </span>
            )}
          {timelineEligible && <Timeline events={timeline} />}
        </>
      )}
    </section>
  );
}
