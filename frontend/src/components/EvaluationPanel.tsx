import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { fetchSessionEvaluation, fetchSessionTimeline, runEvaluation } from "../api";
import { formatCoverage, formatMetric } from "../format";
import type { EvaluationResult, TimelineEvent } from "../types";

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

  useEffect(() => {
    if (!selectedConfig || !selectedTask) {
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
  }, [sessionId, selectedConfig, selectedTask]);

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

  const taskResults = (results ?? []).filter((r) => r.task === selectedTask);
  const selectedResult = taskResults.find((r) => r.configuration_id === selectedConfig) ?? null;

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
                  <th className="px-3 py-2 font-medium">Accuracy</th>
                  <th className="px-3 py-2 font-medium">Precision</th>
                  <th className="px-3 py-2 font-medium">Recall</th>
                  <th className="px-3 py-2 font-medium">F1</th>
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
                    <td className="px-3 py-2 font-mono-data text-slate-200">{formatMetric(r.metrics.accuracy)}</td>
                    <td className="px-3 py-2 font-mono-data text-slate-200">
                      {formatMetric(r.metrics.precision_macro)}
                    </td>
                    <td className="px-3 py-2 font-mono-data text-slate-200">
                      {formatMetric(r.metrics.recall_macro)}
                    </td>
                    <td className="px-3 py-2 font-mono-data text-slate-200">{formatMetric(r.metrics.f1_macro)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {selectedResult && <ConfusionMatrixView result={selectedResult} />}
          {selectedResult && <Timeline events={timeline} />}
        </>
      )}
    </section>
  );
}
