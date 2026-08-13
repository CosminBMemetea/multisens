import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { TopBar } from "../components/TopBar";
import { ComparisonValidityBadge } from "../components/Badge";
import { SensorAdditionCard } from "../components/SensorAdditionCard";
import { AblationCard } from "../components/AblationCard";
import { GeneralComparisonCard } from "../components/GeneralComparisonCard";
import { formatCoverage, formatDelta, formatMetric, labelForMetric } from "../format";
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

// A comparison's own evaluator_type isn't exposed on PairwiseComparison
// (deliberately - see ComparisonMetricTable.tsx's own note); the
// available metric keys already say everything needed. Sort/leaderboard
// options are built dynamically from whatever `reported.metric_deltas`
// keys the actual comparison data has (v0.8, Phase 86) - never a
// hardcoded classification-only list.
type SortMetric = string;

// Sorts by the magnitude of the selected metric's absolute delta,
// largest observed change first - purely a display order, never a
// ranking of "importance." Comparisons where that metric couldn't be
// calculated (null) sort last rather than being dropped.
function sortByMetricMagnitude(comparisons: PairwiseComparison[], metric: SortMetric): PairwiseComparison[] {
  return [...comparisons].sort((a, b) => {
    const av = a.reported.metric_deltas[metric]?.absolute ?? null;
    const bv = b.reported.metric_deltas[metric]?.absolute ?? null;
    if (av === null && bv === null) return 0;
    if (av === null) return 1;
    if (bv === null) return -1;
    return Math.abs(bv) - Math.abs(av);
  });
}

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
  const [sortMetric, setSortMetric] = useState<SortMetric>("");

  // Whatever metric keys this run's evaluator_type actually produced,
  // sorted for a stable option order - never assumed to be
  // classification's own accuracy/precision/recall/F1 set.
  const availableMetrics = useMemo(
    () => (comparisons && comparisons.length > 0 ? Object.keys(comparisons[0].reported.metric_deltas).sort() : []),
    [comparisons],
  );

  useEffect(() => {
    // Keep sortMetric valid as the underlying comparison data changes -
    // falls back to the first available metric, same convention
    // EvaluationPanel's own evaluator-aware column selection uses.
    setSortMetric((current) => (availableMetrics.includes(current) ? current : (availableMetrics[0] ?? "")));
  }, [availableMetrics]);

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

  const sensorAdditions = useMemo(
    () =>
      comparisons
        ? sortByMetricMagnitude(
            comparisons.filter((c) => c.relationship === "direct_addition"),
            sortMetric,
          )
        : [],
    [comparisons, sortMetric],
  );
  const ablations = useMemo(
    () =>
      comparisons
        ? sortByMetricMagnitude(
            comparisons.filter((c) => c.relationship === "direct_removal"),
            sortMetric,
          )
        : [],
    [comparisons, sortMetric],
  );
  const generalComparisons = useMemo(
    () =>
      comparisons
        ? sortByMetricMagnitude(
            comparisons.filter((c) => c.relationship === "general"),
            sortMetric,
          )
        : [],
    [comparisons, sortMetric],
  );

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
                    {/* Whichever metric this evaluator_type actually produced and the
                        "Sort detail cards by" picker is currently set to - never a
                        hardcoded classification-only F1/Recall pair (v0.8, Phase 86). */}
                    <th className="px-3 py-2 font-medium">{sortMetric ? labelForMetric(sortMetric) : "Metric"}</th>
                    <th className="px-3 py-2 font-medium">Δ</th>
                    <th className="px-3 py-2 font-medium">Coverage</th>
                    <th className="px-3 py-2 font-medium">Validity</th>
                  </tr>
                </thead>
                <tbody>
                  {comparisons.length === 0 ? (
                    <tr>
                      <td colSpan={6} className="px-3 py-6 text-center text-slate-500">
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
                          {formatMetric(comparisons[0].reported.baseline.metrics[sortMetric] ?? null)}
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
                            {formatMetric(c.reported.candidate.metrics[sortMetric] ?? null)}
                          </td>
                          <td className="px-3 py-2 font-mono-data text-slate-200">
                            {formatDelta(c.reported.metric_deltas[sortMetric]?.absolute ?? null)}
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

        {comparisons && comparisons.length > 0 && (
          <label className="flex w-fit flex-col gap-1 text-sm text-slate-400">
            Sort detail cards by
            <select
              value={sortMetric}
              onChange={(e) => setSortMetric(e.target.value)}
              className="rounded border border-slate-700 bg-slate-950 px-2 py-1.5 text-slate-100 focus:border-cyan-500/50 focus:outline-none"
            >
              {availableMetrics.map((key) => (
                <option key={key} value={key}>
                  {labelForMetric(key)}
                </option>
              ))}
            </select>
          </label>
        )}

        {sensorAdditions.length > 0 && (
          <section className="flex flex-col gap-3">
            <h2 className="text-xs font-semibold uppercase tracking-wide text-slate-500">Sensor addition</h2>
            <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
              {sensorAdditions.map((c) => (
                <SensorAdditionCard key={c.candidate_configuration_id} comparison={c} />
              ))}
            </div>
          </section>
        )}

        {ablations.length > 0 && (
          <section className="flex flex-col gap-3">
            <h2 className="text-xs font-semibold uppercase tracking-wide text-slate-500">Ablation</h2>
            <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
              {ablations.map((c) => (
                <AblationCard key={c.candidate_configuration_id} comparison={c} />
              ))}
            </div>
          </section>
        )}

        {generalComparisons.length > 0 && (
          <section className="flex flex-col gap-3">
            <h2 className="text-xs font-semibold uppercase tracking-wide text-slate-500">General comparison</h2>
            <p className="text-xs text-slate-600">
              More than one sensor differs between these configurations - deltas below are not attributable to a
              single sensor.
            </p>
            <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
              {generalComparisons.map((c) => (
                <GeneralComparisonCard key={c.candidate_configuration_id} comparison={c} />
              ))}
            </div>
          </section>
        )}
      </main>
    </>
  );
}
