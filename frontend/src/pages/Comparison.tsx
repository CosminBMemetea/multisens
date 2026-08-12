import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { TopBar } from "../components/TopBar";
import { ComparisonValidityBadge } from "../components/Badge";
import { SensorAdditionCard } from "../components/SensorAdditionCard";
import { formatCoverage, formatDelta, formatMetric } from "../format";
import {
  fetchSessionConfigurations,
  fetchSessionGroundTruth,
  fetchSessions,
  runComparison,
} from "../api";
import type { ConfigurationSummary, PairwiseComparison, Session } from "../types";

const RELATIONSHIP_LABELS: Record<PairwiseComparison["relationship"], string> = {
  direct_addition: "Sensor added",
  direct_removal: "Sensor removed",
  general: "General comparison",
};

export function Comparison() {
  const [searchParams, setSearchParams] = useSearchParams();

  const [sessions, setSessions] = useState<Session[]>([]);
  const [sessionId, setSessionId] = useState(searchParams.get("session") ?? "");
  const [tasks, setTasks] = useState<string[]>([]);
  const [task, setTask] = useState(searchParams.get("task") ?? "");
  const [configurations, setConfigurations] = useState<ConfigurationSummary[]>([]);
  const [baselineId, setBaselineId] = useState(searchParams.get("baseline") ?? "");

  const [comparisons, setComparisons] = useState<PairwiseComparison[] | null>(null);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchSessions()
      .then(setSessions)
      .catch((err) => setError(String(err)));
  }, []);

  useEffect(() => {
    if (!sessionId) {
      setTasks([]);
      return;
    }
    fetchSessionGroundTruth(sessionId)
      .then((events) => setTasks([...new Set(events.map((e) => e.task))].sort()))
      .catch((err) => setError(String(err)));
  }, [sessionId]);

  useEffect(() => {
    if (!sessionId || !task) {
      setConfigurations([]);
      return;
    }
    fetchSessionConfigurations(sessionId, task)
      .then(setConfigurations)
      .catch((err) => setError(String(err)));
  }, [sessionId, task]);

  // Only configurations that have already been evaluated can serve as a
  // baseline or candidate - /compare requires a persisted EvaluationResult
  // for both sides rather than triggering evaluation as a side effect.
  const evaluatedConfigurations = useMemo(
    () => configurations.filter((c) => c.matched_samples !== null),
    [configurations],
  );

  useEffect(() => {
    setSearchParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        if (sessionId) next.set("session", sessionId); else next.delete("session");
        if (task) next.set("task", task); else next.delete("task");
        if (baselineId) next.set("baseline", baselineId); else next.delete("baseline");
        return next;
      },
      { replace: true },
    );
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId, task, baselineId]);

  async function handleRunComparison() {
    if (!sessionId || !task || !baselineId) return;
    setRunning(true);
    setError(null);
    setComparisons(null);
    try {
      const result = await runComparison(sessionId, { task, baseline_configuration_id: baselineId });
      setComparisons(result.comparisons);
    } catch (err) {
      setError(String(err));
    } finally {
      setRunning(false);
    }
  }

  return (
    <>
      <TopBar />
      <main className="mx-auto flex max-w-6xl flex-col gap-6 p-6">
        <h1 className="text-xl font-semibold text-slate-100">Comparison</h1>

        <section className="flex flex-wrap items-end gap-4 rounded border border-slate-800 bg-slate-900/40 p-4">
          <label className="flex flex-col gap-1 text-sm text-slate-400">
            Session
            <select
              value={sessionId}
              onChange={(e) => {
                setSessionId(e.target.value);
                setTask("");
                setBaselineId("");
                setComparisons(null);
              }}
              className="rounded border border-slate-700 bg-slate-950 px-2 py-1.5 text-slate-100 focus:border-cyan-500/50 focus:outline-none"
            >
              <option value="">Select a session…</option>
              {sessions.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.name}
                </option>
              ))}
            </select>
          </label>

          <label className="flex flex-col gap-1 text-sm text-slate-400">
            Task
            <select
              value={task}
              onChange={(e) => {
                setTask(e.target.value);
                setBaselineId("");
                setComparisons(null);
              }}
              disabled={tasks.length === 0}
              className="rounded border border-slate-700 bg-slate-950 px-2 py-1.5 text-slate-100 focus:border-cyan-500/50 focus:outline-none disabled:opacity-50"
            >
              <option value="">Select a task…</option>
              {tasks.map((t) => (
                <option key={t} value={t}>
                  {t}
                </option>
              ))}
            </select>
          </label>

          <label className="flex flex-col gap-1 text-sm text-slate-400">
            Baseline configuration
            <select
              value={baselineId}
              onChange={(e) => {
                setBaselineId(e.target.value);
                setComparisons(null);
              }}
              disabled={evaluatedConfigurations.length === 0}
              className="rounded border border-slate-700 bg-slate-950 px-2 py-1.5 text-slate-100 focus:border-cyan-500/50 focus:outline-none disabled:opacity-50"
            >
              <option value="">Select a baseline…</option>
              {evaluatedConfigurations.map((c) => (
                <option key={c.configuration_id} value={c.configuration_id}>
                  {c.configuration_id}
                </option>
              ))}
            </select>
          </label>

          <button
            onClick={handleRunComparison}
            disabled={!baselineId || running}
            className="rounded border border-cyan-500/40 bg-cyan-500/10 px-3 py-1.5 text-sm font-medium text-cyan-400 hover:bg-cyan-500/20 disabled:opacity-50"
          >
            {running ? "Comparing…" : "Compare"}
          </button>
        </section>

        {task && evaluatedConfigurations.length < 2 && (
          <div className="rounded border border-slate-800 bg-slate-900/40 p-3 text-sm text-slate-500">
            Fewer than two evaluated configurations for this task - nothing to compare yet. Run
            evaluation for at least one more configuration on the session's detail page.
          </div>
        )}

        {error && (
          <div className="rounded border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-400">{error}</div>
        )}

        {comparisons && (
          <section className="flex flex-col gap-2">
            <h2 className="text-xs font-semibold uppercase tracking-wide text-slate-500">
              Configuration comparison
            </h2>
            <div className="overflow-x-auto rounded border border-slate-800">
              <table className="w-full text-left text-sm">
                <thead className="border-b border-slate-800 bg-slate-900/60 text-xs uppercase tracking-wide text-slate-500">
                  <tr>
                    <th className="px-3 py-2 font-medium">Configuration</th>
                    <th className="px-3 py-2 font-medium">Relationship</th>
                    <th className="px-3 py-2 font-medium">F1</th>
                    <th className="px-3 py-2 font-medium">ΔF1</th>
                    <th className="px-3 py-2 font-medium">Recall</th>
                    <th className="px-3 py-2 font-medium">ΔRecall</th>
                    <th className="px-3 py-2 font-medium">Coverage</th>
                    <th className="px-3 py-2 font-medium">Validity</th>
                  </tr>
                </thead>
                <tbody>
                  {comparisons.length === 0 ? (
                    <tr>
                      <td colSpan={8} className="px-3 py-6 text-center text-slate-500">
                        No comparable configurations found.
                      </td>
                    </tr>
                  ) : (
                    <>
                      {/* Baseline itself, once - all comparisons in one run share the
                          same baseline, so its own metrics are read from the first
                          comparison's `reported.baseline` rather than re-fetched. */}
                      <tr className="border-b border-slate-800/60 bg-slate-900/40">
                        <td className="px-3 py-2 font-mono-data text-slate-200">
                          {comparisons[0].baseline_configuration_id}
                          <span className="ml-2 text-[10px] uppercase text-slate-500">baseline</span>
                        </td>
                        <td className="px-3 py-2 text-slate-600">—</td>
                        <td className="px-3 py-2 font-mono-data text-slate-200">
                          {formatMetric(comparisons[0].reported.baseline.metrics.f1_macro ?? null)}
                        </td>
                        <td className="px-3 py-2 font-mono-data text-slate-600">—</td>
                        <td className="px-3 py-2 font-mono-data text-slate-200">
                          {formatMetric(comparisons[0].reported.baseline.metrics.recall_macro ?? null)}
                        </td>
                        <td className="px-3 py-2 font-mono-data text-slate-600">—</td>
                        <td className="px-3 py-2 font-mono-data text-slate-200">
                          {formatCoverage(
                            comparisons[0].reported.baseline.matched_samples,
                            comparisons[0].reported.baseline.sample_count,
                          )}
                        </td>
                        <td className="px-3 py-2 text-slate-600">—</td>
                      </tr>
                      {comparisons.map((c) => (
                        <tr key={c.candidate_configuration_id} className="border-b border-slate-800/60 last:border-0">
                          <td className="px-3 py-2 font-mono-data text-slate-200">
                            {c.candidate_configuration_id}
                          </td>
                          <td className="px-3 py-2 text-slate-400">{RELATIONSHIP_LABELS[c.relationship]}</td>
                          <td className="px-3 py-2 font-mono-data text-slate-200">
                            {formatMetric(c.reported.candidate.metrics.f1_macro ?? null)}
                          </td>
                          <td className="px-3 py-2 font-mono-data text-slate-200">
                            {formatDelta(c.reported.metric_deltas.f1_macro?.absolute ?? null)}
                          </td>
                          <td className="px-3 py-2 font-mono-data text-slate-200">
                            {formatMetric(c.reported.candidate.metrics.recall_macro ?? null)}
                          </td>
                          <td className="px-3 py-2 font-mono-data text-slate-200">
                            {formatDelta(c.reported.metric_deltas.recall_macro?.absolute ?? null)}
                          </td>
                          <td className="px-3 py-2 font-mono-data text-slate-200">
                            {formatCoverage(c.reported.candidate.matched_samples, c.reported.candidate.sample_count)}
                          </td>
                          <td className="px-3 py-2">
                            <ComparisonValidityBadge validity={c.validity} />
                          </td>
                        </tr>
                      ))}
                    </>
                  )}
                </tbody>
              </table>
            </div>
          </section>
        )}

        {comparisons && comparisons.some((c) => c.relationship === "direct_addition") && (
          <section className="flex flex-col gap-3">
            <h2 className="text-xs font-semibold uppercase tracking-wide text-slate-500">Sensor addition</h2>
            <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
              {comparisons
                .filter((c) => c.relationship === "direct_addition")
                .map((c) => (
                  <SensorAdditionCard key={c.candidate_configuration_id} comparison={c} />
                ))}
            </div>
          </section>
        )}
      </main>
    </>
  );
}
