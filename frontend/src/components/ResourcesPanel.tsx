import { useEffect, useMemo, useState } from "react";
import { fetchResourceMetrics, fetchSessionResourceObservations, fetchSessions, runTradeoffs } from "../api";
import { formatFractionPercent, formatResourceValue } from "../format";
import { PolicyStatusBadge } from "./PolicyStatusBadge";
import { QualificationBadge } from "./QualificationBadge";
import { ResourceQualityBadge } from "./ResourceQualityBadge";
import { ResourceTimeSeriesChart } from "./ResourceTimeSeriesChart";
import {
  RESOURCE_METRIC_LABELS,
  SUPPORTED_RESOURCE_METRICS,
} from "../types";
import type {
  AcceptanceOperator,
  ConfigurationTradeoff,
  DecisionPolicy,
  ParetoDirection,
  ResourceMetric,
  ResourceMetricSummary,
  ResourceObservation,
  Session,
  TradeoffResponse,
} from "../types";

// Every dimension's natural improvement direction - fixed and
// non-editable, never an arbitrary caller-assigned weighting. Mirrors
// the v0.7 architecture review's own "minimize: sensor_count, cpu,
// memory, bandwidth, latency; maximize: coverage, completeness" split;
// fps is the one metric where higher is unambiguously better.
const PARETO_DIRECTIONS: Record<string, ParetoDirection> = {
  sensor_count: "minimize",
  requirement_coverage: "maximize",
  evidence_completeness: "maximize",
  cpu_percent: "minimize",
  memory_mb: "minimize",
  network_receive_mbps: "minimize",
  network_transmit_mbps: "minimize",
  pipeline_latency_ms: "minimize",
  fps: "maximize",
};

const PARETO_DIMENSION_LABELS: Record<string, string> = {
  sensor_count: "Streams",
  requirement_coverage: "Coverage",
  evidence_completeness: "Completeness",
  ...RESOURCE_METRIC_LABELS,
};

interface ResourcesPanelProps {
  profileId: string;
  synthetic: boolean;
}

// A starting point only, editable nowhere on this tab (the Decision tab
// already owns the full editable policy form) - Coverage/Streams here
// exist purely as context alongside resource cost, not as this tab's own
// decision workflow. Same shape as DecisionPanel's own DEMO_POLICY.
const DEMO_POLICY: DecisionPolicy = {
  minimum_requirement_coverage: 1.0,
  minimum_evidence_completeness: 0.95,
  mandatory_requirements_must_pass: false,
  objective: "minimize_sensor_count",
};

function useSessions() {
  const [sessions, setSessions] = useState<Session[] | null>(null);
  useEffect(() => {
    let cancelled = false;
    fetchSessions()
      .then((s) => {
        if (!cancelled) setSessions(s);
      })
      .catch(() => {
        if (!cancelled) setSessions([]);
      });
    return () => {
      cancelled = true;
    };
  }, []);
  return sessions;
}

// The backend's current resource-metric vocabulary (v0.9 bug hunt, issue
// #116) - starts from the original six built-in metrics (never a broken
// empty tab before the fetch resolves, and a safe fallback if the
// backend is unreachable or predates this route), replaced with the
// real list once fetched - so a RESOURCE_COLLECTOR plugin's own metrics
// become requestable/selectable without a frontend rebuild.
function useResourceMetrics(): string[] {
  const [metrics, setMetrics] = useState<string[]>([...SUPPORTED_RESOURCE_METRICS]);
  useEffect(() => {
    let cancelled = false;
    fetchResourceMetrics()
      .then((m) => {
        if (!cancelled) setMetrics(m);
      })
      .catch(() => {
        // Leave the built-in fallback in place - never an empty/broken tab.
      });
    return () => {
      cancelled = true;
    };
  }, []);
  return metrics;
}

interface ResourceConstraintInput {
  metric: string;
  operator: AcceptanceOperator;
  value: number;
}

interface ResourceComparisonInput {
  baseline_configuration_id: string;
  candidate_configuration_id: string;
}

// One consolidated call, same "gap_analysis on /decision-analysis"
// posture the backend itself already takes - constraints/pareto
// dimensions/comparison are all optional parts of the same request, not
// separate fetches, since they always need the same evidence this call
// already gathers.
function useTradeoffs(
  profileId: string,
  sessionId: string,
  resourceMetrics: string[],
  resourceConstraints: ResourceConstraintInput[],
  paretoDimensions: Record<string, ParetoDirection>,
  resourceComparison: ResourceComparisonInput | null,
) {
  const [result, setResult] = useState<TradeoffResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const key = JSON.stringify({ resourceMetrics, resourceConstraints, paretoDimensions, resourceComparison });

  useEffect(() => {
    if (!sessionId) {
      setResult(null);
      setError(null);
      return;
    }
    let cancelled = false;
    setError(null);
    runTradeoffs(profileId, {
      policy: DEMO_POLICY,
      session_id: sessionId,
      resource_metrics: resourceMetrics,
      resource_constraints: resourceConstraints,
      pareto_dimensions: paretoDimensions,
      resource_comparison: resourceComparison ?? undefined,
    })
      .then((r) => {
        if (!cancelled) setResult(r);
      })
      .catch((err) => {
        if (!cancelled) setError(String(err));
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [profileId, sessionId, key]);

  return { result, error };
}

interface DrillDownTarget {
  configurationId: string;
  metric: ResourceMetric;
  summary: ResourceMetricSummary;
  platformId: string;
}

function ResourceMetricDrillDown({
  sessionId,
  target,
  onClose,
}: {
  sessionId: string;
  target: DrillDownTarget;
  onClose: () => void;
}) {
  const [observations, setObservations] = useState<ResourceObservation[] | null>(null);

  useEffect(() => {
    let cancelled = false;
    fetchSessionResourceObservations(sessionId, {
      configuration_id: target.configurationId,
      metric: target.metric,
    })
      .then((rows) => {
        if (!cancelled) setObservations(rows);
      })
      .catch(() => {
        if (!cancelled) setObservations([]);
      });
    return () => {
      cancelled = true;
    };
  }, [sessionId, target.configurationId, target.metric]);

  const { summary } = target;
  const realValued = (observations ?? []).filter((o) => o.value !== null);
  const chartPoints = realValued.map((o) => ({ timestamp: o.started_at, value: o.value as number }));

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4"
      onClick={onClose}
      role="presentation"
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label={`${RESOURCE_METRIC_LABELS[target.metric]} detail`}
        className="flex max-h-[85vh] w-full max-w-md flex-col gap-3 overflow-y-auto rounded-lg border border-slate-700 bg-slate-900 p-5"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between gap-3">
          <h2 className="text-sm font-semibold text-slate-100">
            {RESOURCE_METRIC_LABELS[target.metric]} — {target.configurationId}
          </h2>
          <button onClick={onClose} aria-label="Close" className="text-lg leading-none text-slate-500 hover:text-slate-300">
            ×
          </button>
        </div>

        <ResourceQualityBadge quality={summary.quality} platformId={target.platformId} />

        <div className="grid grid-cols-3 gap-2 font-mono-data text-xs text-slate-300">
          <div>
            <div className="text-slate-500">mean</div>
            {formatResourceValue(summary.mean, summary.unit)}
          </div>
          <div>
            <div className="text-slate-500">median</div>
            {formatResourceValue(summary.median, summary.unit)}
          </div>
          <div>
            <div className="text-slate-500">p95</div>
            {formatResourceValue(summary.p95, summary.unit)}
          </div>
          <div>
            <div className="text-slate-500">min</div>
            {formatResourceValue(summary.min, summary.unit)}
          </div>
          <div>
            <div className="text-slate-500">max</div>
            {formatResourceValue(summary.max, summary.unit)}
          </div>
          <div>
            <div className="text-slate-500">samples</div>
            {summary.sample_count}
          </div>
        </div>

        {observations === null && <p className="text-xs text-slate-500">Loading observation detail…</p>}

        {observations !== null && realValued.length > 0 && (
          <div className="flex flex-col gap-2">
            <h3 className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">Over this session</h3>
            <ResourceTimeSeriesChart points={chartPoints} unit={summary.unit} />
          </div>
        )}

        {observations !== null && observations.length > 0 && (
          <div className="flex flex-col gap-1">
            <h3 className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">Contributing rows</h3>
            <ul className="flex flex-col gap-1 font-mono-data text-[11px] text-slate-400">
              {observations.map((o) => (
                <li key={o.id} className="flex items-center justify-between gap-2 rounded border border-slate-800 px-2 py-1">
                  <span>{new Date(o.started_at).toLocaleTimeString()}</span>
                  <span>{formatResourceValue(o.value, o.unit)}</span>
                  <ResourceQualityBadge quality={o.quality} />
                  <span className="truncate text-slate-600">{o.source}</span>
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </div>
  );
}

function ResourceTable({
  configurations,
  onOpenDrillDown,
}: {
  configurations: ConfigurationTradeoff[];
  onOpenDrillDown: (target: DrillDownTarget) => void;
}) {
  function cell(tradeoff: ConfigurationTradeoff, metric: ResourceMetric) {
    const summary = tradeoff.resource_profile?.metrics[metric];
    const platformId = tradeoff.resource_profile?.platform_id ?? "unknown";
    if (!summary) {
      return <span className="font-mono-data text-slate-700">—</span>;
    }
    return (
      <button
        onClick={() => onOpenDrillDown({ configurationId: tradeoff.configuration_id, metric, summary, platformId })}
        className="flex flex-col items-start gap-0.5 text-left hover:opacity-80"
      >
        <span className="font-mono-data text-slate-200">{formatResourceValue(summary.mean, summary.unit)}</span>
        <ResourceQualityBadge quality={summary.quality} />
      </button>
    );
  }

  function networkCell(tradeoff: ConfigurationTradeoff) {
    const recv = tradeoff.resource_profile?.metrics["network_receive_mbps"];
    const send = tradeoff.resource_profile?.metrics["network_transmit_mbps"];
    if (!recv && !send) return <span className="font-mono-data text-slate-700">—</span>;
    return (
      <div className="flex flex-col gap-0.5 font-mono-data text-slate-200">
        <button
          onClick={() =>
            recv &&
            onOpenDrillDown({
              configurationId: tradeoff.configuration_id,
              metric: "network_receive_mbps",
              summary: recv,
              platformId: tradeoff.resource_profile?.platform_id ?? "unknown",
            })
          }
          className="text-left hover:opacity-80"
        >
          ↓ {formatResourceValue(recv?.mean ?? null, "Mbps")}
        </button>
        <button
          onClick={() =>
            send &&
            onOpenDrillDown({
              configurationId: tradeoff.configuration_id,
              metric: "network_transmit_mbps",
              summary: send,
              platformId: tradeoff.resource_profile?.platform_id ?? "unknown",
            })
          }
          className="text-left hover:opacity-80"
        >
          ↑ {formatResourceValue(send?.mean ?? null, "Mbps")}
        </button>
      </div>
    );
  }

  return (
    <div className="overflow-x-auto rounded border border-slate-800">
      <table className="w-full text-left text-sm">
        <thead className="border-b border-slate-800 bg-slate-900/60 text-xs uppercase tracking-wide text-slate-500">
          <tr>
            <th className="px-3 py-2 font-medium">Configuration</th>
            <th className="px-3 py-2 font-medium">Streams</th>
            <th className="px-3 py-2 font-medium">Coverage</th>
            <th className="px-3 py-2 font-medium">CPU</th>
            <th className="px-3 py-2 font-medium">RAM</th>
            <th className="px-3 py-2 font-medium">Network</th>
            <th className="px-3 py-2 font-medium">Latency</th>
          </tr>
        </thead>
        <tbody>
          {configurations.map((c) => (
            <tr key={c.configuration_id} className="border-b border-slate-800/60 last:border-0 align-top">
              <td className="px-3 py-2 font-mono-data text-slate-200">
                <div className="flex flex-col gap-1">
                  {c.configuration_id}
                  <PolicyStatusBadge status={c.policy_status} />
                </div>
              </td>
              <td className="px-3 py-2 font-mono-data text-slate-300">{c.sensor_count}</td>
              <td className="px-3 py-2 font-mono-data text-slate-300">
                {formatFractionPercent(c.requirement_coverage)}
              </td>
              <td className="px-3 py-2">{cell(c, "cpu_percent")}</td>
              <td className="px-3 py-2">{cell(c, "memory_mb")}</td>
              <td className="px-3 py-2">{networkCell(c)}</td>
              <td className="px-3 py-2">{cell(c, "pipeline_latency_ms")}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

const inputClass =
  "rounded border border-slate-700 bg-slate-950 px-2 py-1.5 text-slate-100 focus:border-cyan-500/50 focus:outline-none";

const CONSTRAINT_STATUS_STYLES: Record<string, string> = {
  pass: "text-emerald-400",
  fail: "text-red-400",
  na: "text-amber-400",
};

function dimensionLabel(dim: string): string {
  return PARETO_DIMENSION_LABELS[dim] ?? dim;
}

// Reuses the exact acceptance-criterion editing shape the Decision tab's
// policy form already established (metric/operator/value) - not a new
// grammar, matching AcceptanceCriterion directly (see
// docs/decision-support.md#resource-constraints).
function ResourceConstraintForm({
  constraints,
  onChange,
  availableMetrics,
}: {
  constraints: ResourceConstraintInput[];
  onChange: (next: ResourceConstraintInput[]) => void;
  // A plain string, not the closed ResourceMetric union (v0.9 bug hunt,
  // issue #116) - the available list is now whatever the backend
  // actually supports at runtime, which can include a plugin-declared
  // metric this frontend build has never heard of.
  availableMetrics: string[];
}) {
  function updateAt(index: number, patch: Partial<ResourceConstraintInput>) {
    onChange(constraints.map((c, i) => (i === index ? { ...c, ...patch } : c)));
  }
  function removeAt(index: number) {
    onChange(constraints.filter((_, i) => i !== index));
  }
  function add() {
    onChange([...constraints, { metric: availableMetrics[0] ?? "cpu_percent", operator: "<=", value: 50 }]);
  }

  return (
    <section className="flex flex-col gap-2 rounded border border-slate-800 bg-slate-900/40 p-4">
      <h2 className="text-xs font-semibold uppercase tracking-wide text-slate-500">Resource constraints</h2>
      {constraints.length === 0 && (
        <p className="text-xs text-slate-600">
          No constraints yet — every configuration's qualification stays undetermined until at least one is added.
        </p>
      )}
      {constraints.map((c, i) => (
        <div key={i} className="flex items-center gap-2">
          <select value={c.metric} onChange={(e) => updateAt(i, { metric: e.target.value })} className={inputClass}>
            {availableMetrics.map((m) => (
              <option key={m} value={m}>
                {RESOURCE_METRIC_LABELS[m as ResourceMetric] ?? m}
              </option>
            ))}
          </select>
          <select
            value={c.operator}
            onChange={(e) => updateAt(i, { operator: e.target.value as AcceptanceOperator })}
            className={inputClass}
          >
            {(["<=", "<", ">=", ">", "=="] as AcceptanceOperator[]).map((op) => (
              <option key={op} value={op}>
                {op}
              </option>
            ))}
          </select>
          <input
            type="number"
            value={c.value}
            onChange={(e) => updateAt(i, { value: Number(e.target.value) })}
            className={`${inputClass} w-24`}
          />
          <button onClick={() => removeAt(i)} className="text-xs text-slate-500 hover:text-red-400">
            Remove
          </button>
        </div>
      ))}
      <button
        onClick={add}
        className="self-start rounded border border-slate-700 px-2 py-1 text-xs text-slate-300 hover:border-cyan-500/50"
      >
        + Add constraint
      </button>
    </section>
  );
}

// One row per configuration - qualification is never computed client-
// side, always the exact evaluate_resource_qualification output the
// backend already returned alongside its per-constraint PASS/FAIL/N/A
// breakdown (constraint_results), so this table can never silently
// disagree with the engine that decided it.
function QualificationTable({ configurations }: { configurations: ConfigurationTradeoff[] }) {
  const withConstraints = configurations.filter((c) => c.constraint_results.length > 0);
  if (withConstraints.length === 0) return null;
  const columns = withConstraints[0].constraint_results;

  return (
    <div className="overflow-x-auto rounded border border-slate-800">
      <table className="w-full text-left text-sm">
        <thead className="border-b border-slate-800 bg-slate-900/60 text-xs uppercase tracking-wide text-slate-500">
          <tr>
            <th className="px-3 py-2 font-medium">Configuration</th>
            <th className="px-3 py-2 font-medium">Qualification</th>
            {columns.map((r, i) => (
              <th key={i} className="px-3 py-2 font-medium">
                {dimensionLabel(r.metric)} {r.operator} {r.threshold}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {configurations.map((c) => (
            <tr key={c.configuration_id} className="border-b border-slate-800/60 last:border-0">
              <td className="px-3 py-2 font-mono-data text-slate-200">{c.configuration_id}</td>
              <td className="px-3 py-2">
                <QualificationBadge status={c.qualification} />
              </td>
              {columns.map((_, i) => {
                const r = c.constraint_results[i];
                if (!r) return <td key={i} className="px-3 py-2 font-mono-data text-slate-700">—</td>;
                return (
                  <td key={i} className="px-3 py-2 font-mono-data">
                    <span className={CONSTRAINT_STATUS_STYLES[r.status]}>{r.status.toUpperCase()}</span>{" "}
                    <span className="text-xs text-slate-500">
                      {r.observed === null ? "—" : r.observed.toFixed(1)}
                    </span>
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// Baseline/candidate comparison - a separate fetch trigger folded into
// the same /tradeoffs call (see useTradeoffs's own docstring), never a
// second endpoint. Comparability warnings are always shown alongside
// the numbers, never hidden and never silently blocking them.
function ResourceComparisonSection({
  configurations,
  comparison,
  onCompare,
}: {
  configurations: ConfigurationTradeoff[];
  comparison: TradeoffResponse["resource_comparison"];
  onCompare: (input: ResourceComparisonInput | null) => void;
}) {
  const withEvidence = useMemo(() => configurations.filter((c) => c.policy_status !== null), [configurations]);
  const [baselineId, setBaselineId] = useState("");
  const [candidateId, setCandidateId] = useState("");

  useEffect(() => {
    if (withEvidence.length > 0 && baselineId === "") setBaselineId(withEvidence[0].configuration_id);
  }, [withEvidence, baselineId]);

  useEffect(() => {
    if (baselineId && candidateId && baselineId !== candidateId) {
      onCompare({ baseline_configuration_id: baselineId, candidate_configuration_id: candidateId });
    } else {
      onCompare(null);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [baselineId, candidateId]);

  return (
    <section className="flex flex-col gap-3">
      <h2 className="text-xs font-semibold uppercase tracking-wide text-slate-500">Resource comparison</h2>
      <div className="flex flex-wrap items-end gap-4 rounded border border-slate-800 bg-slate-900/40 p-4">
        <label className="flex flex-col gap-1 text-sm text-slate-400">
          Baseline
          <select value={baselineId} onChange={(e) => setBaselineId(e.target.value)} className={inputClass}>
            {withEvidence.map((c) => (
              <option key={c.configuration_id} value={c.configuration_id}>
                {c.configuration_id}
              </option>
            ))}
          </select>
        </label>
        <label className="flex flex-col gap-1 text-sm text-slate-400">
          Candidate
          <select value={candidateId} onChange={(e) => setCandidateId(e.target.value)} className={inputClass}>
            <option value="">None</option>
            {withEvidence
              .filter((c) => c.configuration_id !== baselineId)
              .map((c) => (
                <option key={c.configuration_id} value={c.configuration_id}>
                  {c.configuration_id}
                </option>
              ))}
          </select>
        </label>
      </div>

      {comparison && (
        <div className="flex flex-col gap-2">
          {comparison.comparability.warnings.length > 0 && (
            <div className="flex flex-col gap-1 rounded border border-amber-500/30 bg-amber-500/10 p-2 text-xs text-amber-300">
              {comparison.comparability.warnings.map((w, i) => (
                <div key={i}>⚠ {w}</div>
              ))}
            </div>
          )}
          <div className="overflow-x-auto rounded border border-slate-800">
            <table className="w-full text-left text-sm">
              <thead className="border-b border-slate-800 bg-slate-900/60 text-xs uppercase tracking-wide text-slate-500">
                <tr>
                  <th className="px-3 py-2 font-medium">Metric</th>
                  <th className="px-3 py-2 font-medium">Baseline</th>
                  <th className="px-3 py-2 font-medium">Candidate</th>
                  <th className="px-3 py-2 font-medium">Observed delta</th>
                </tr>
              </thead>
              <tbody>
                {comparison.metric_deltas.map((d) => (
                  <tr key={d.metric} className="border-b border-slate-800/60 last:border-0 font-mono-data">
                    <td className="px-3 py-2 text-slate-300">{dimensionLabel(d.metric)}</td>
                    <td className="px-3 py-2 text-slate-200">{formatResourceValue(d.baseline, d.unit)}</td>
                    <td className="px-3 py-2 text-slate-200">{formatResourceValue(d.candidate, d.unit)}</td>
                    <td className="px-3 py-2 text-slate-200">
                      {d.delta === null ? "—" : `${d.delta > 0 ? "+" : ""}${d.delta.toFixed(1)} ${d.unit}`}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </section>
  );
}

function tradeoffDimensionValue(c: ConfigurationTradeoff, dimension: string): number | null {
  if (dimension === "sensor_count") return c.sensor_count;
  if (dimension === "requirement_coverage") return c.requirement_coverage;
  if (dimension === "evidence_completeness") return c.evidence_completeness;
  return c.resource_profile?.metrics[dimension]?.mean ?? null;
}

// User-selected x/y dimensions only - never an arbitrary weighted
// composite score. Only dimensions with at least one real value
// somewhere in this session are offered, per this phase's own
// acceptance criterion.
function ResourceParetoSection({
  configurations,
  paretoFrontIds,
  dimensions,
  onChangeDimensions,
  availableDims,
}: {
  configurations: ConfigurationTradeoff[];
  paretoFrontIds: string[];
  dimensions: [string, string];
  onChangeDimensions: (next: [string, string]) => void;
  availableDims: string[];
}) {
  const evaluated = configurations.filter((c) => c.policy_status !== null);
  const front = evaluated.filter((c) => paretoFrontIds.includes(c.configuration_id));
  const dominated = evaluated.filter((c) => !paretoFrontIds.includes(c.configuration_id));
  const [x, y] = dimensions;

  return (
    <section className="flex flex-col gap-3">
      <h2 className="text-xs font-semibold uppercase tracking-wide text-slate-500">Resource Pareto front</h2>
      <div className="flex flex-wrap items-end gap-4 rounded border border-slate-800 bg-slate-900/40 p-4">
        <label className="flex flex-col gap-1 text-sm text-slate-400">
          X dimension ({PARETO_DIRECTIONS[x]})
          <select value={x} onChange={(e) => onChangeDimensions([e.target.value, y])} className={inputClass}>
            {availableDims.map((d) => (
              <option key={d} value={d}>
                {dimensionLabel(d)}
              </option>
            ))}
          </select>
        </label>
        <label className="flex flex-col gap-1 text-sm text-slate-400">
          Y dimension ({PARETO_DIRECTIONS[y]})
          <select value={y} onChange={(e) => onChangeDimensions([x, e.target.value])} className={inputClass}>
            {availableDims.map((d) => (
              <option key={d} value={d}>
                {dimensionLabel(d)}
              </option>
            ))}
          </select>
        </label>
      </div>

      {front.length === 0 ? (
        <p className="text-sm text-slate-500">No configuration has evidence for both selected dimensions yet.</p>
      ) : (
        <div className="overflow-x-auto rounded border border-slate-800">
          <table className="w-full text-left text-sm">
            <thead className="border-b border-slate-800 bg-slate-900/60 text-xs uppercase tracking-wide text-slate-500">
              <tr>
                <th className="px-3 py-2 font-medium">Configuration</th>
                <th className="px-3 py-2 font-medium">{dimensionLabel(x)}</th>
                <th className="px-3 py-2 font-medium">{dimensionLabel(y)}</th>
              </tr>
            </thead>
            <tbody>
              {front.map((c) => (
                <tr key={c.configuration_id} className="border-b border-slate-800/60 last:border-0 font-mono-data">
                  <td className="px-3 py-2 text-slate-200">{c.configuration_id}</td>
                  <td className="px-3 py-2 text-slate-200">{tradeoffDimensionValue(c, x) ?? "—"}</td>
                  <td className="px-3 py-2 text-slate-200">{tradeoffDimensionValue(c, y) ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {dominated.length > 0 && (
        <details className="rounded border border-slate-800">
          <summary className="cursor-pointer select-none px-3 py-2 text-xs font-semibold uppercase tracking-wide text-slate-500">
            {dominated.length} dominated configuration{dominated.length === 1 ? "" : "s"}
          </summary>
          <table className="w-full text-left text-sm">
            <tbody>
              {dominated.map((c) => (
                <tr key={c.configuration_id} className="border-t border-slate-800/60 font-mono-data">
                  <td className="px-3 py-2 text-slate-400">{c.configuration_id}</td>
                  <td className="px-3 py-2 text-slate-400">{tradeoffDimensionValue(c, x) ?? "—"}</td>
                  <td className="px-3 py-2 text-slate-400">{tradeoffDimensionValue(c, y) ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </details>
      )}
    </section>
  );
}

export function ResourcesPanel({ profileId, synthetic }: ResourcesPanelProps) {
  const sessions = useSessions();
  const resourceMetrics = useResourceMetrics();
  const [sessionId, setSessionId] = useState("");
  const [drillDown, setDrillDown] = useState<DrillDownTarget | null>(null);
  const [constraints, setConstraints] = useState<ResourceConstraintInput[]>([]);
  const [resourceComparison, setResourceComparison] = useState<ResourceComparisonInput | null>(null);
  const [dimensions, setDimensions] = useState<[string, string]>(["sensor_count", "requirement_coverage"]);

  const paretoDimensions = useMemo(
    () => ({ [dimensions[0]]: PARETO_DIRECTIONS[dimensions[0]], [dimensions[1]]: PARETO_DIRECTIONS[dimensions[1]] }),
    [dimensions],
  );

  const { result, error } = useTradeoffs(
    profileId, sessionId, resourceMetrics, constraints, paretoDimensions, resourceComparison,
  );

  useEffect(() => {
    if (sessions && sessions.length > 0 && sessionId === "") setSessionId(sessions[0].id);
  }, [sessions, sessionId]);

  const availableDims = useMemo(() => {
    if (!result) return ["sensor_count", "requirement_coverage", "evidence_completeness"];
    const dims = new Set<string>(["sensor_count", "requirement_coverage", "evidence_completeness"]);
    for (const c of result.configurations) {
      for (const metric of Object.keys(c.resource_profile?.metrics ?? {})) dims.add(metric);
    }
    return [...dims];
  }, [result]);

  // Filtered against the backend's own live-fetched vocabulary (v0.9 bug
  // hunt, issue #116), not the frontend's hardcoded fallback constant -
  // a plugin-declared metric that actually came back with real evidence
  // in `result` is now offered in the constraint-builder dropdown too.
  const availableConstraintMetrics = useMemo(
    () => availableDims.filter((d) => resourceMetrics.includes(d)),
    [availableDims, resourceMetrics],
  );

  return (
    <div className="flex flex-col gap-4">
      {synthetic && (
        <div className="rounded border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-sm font-medium text-amber-300">
          ⚠ SYNTHETIC RESOURCE DATA — these CPU/memory/network/latency values are generated to demonstrate
          MultiSens functionality and do not represent measured performance of physical or simulated hardware.
        </div>
      )}

      <div className="flex flex-wrap items-end gap-4 rounded border border-slate-800 bg-slate-900/40 p-4">
        <label className="flex flex-col gap-1 text-sm text-slate-400">
          Session
          <select
            value={sessionId}
            onChange={(e) => setSessionId(e.target.value)}
            className="w-64 rounded border border-slate-700 bg-slate-950 px-2 py-1.5 text-slate-100 focus:border-cyan-500/50 focus:outline-none"
          >
            <option value="">Select a session</option>
            {(sessions ?? []).map((s) => (
              <option key={s.id} value={s.id}>
                {s.name}
              </option>
            ))}
          </select>
        </label>
        <p className="text-xs text-slate-600">
          Resource evidence is scoped to one session at a time - see docs/decision-support.md for why.
        </p>
      </div>

      {error && <div className="rounded border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-400">{error}</div>}

      {sessionId === "" && !error && (
        <p className="text-sm text-slate-500">Select a session with resource observations to view its trade-offs.</p>
      )}

      {sessionId !== "" && result === null && !error && (
        <p className="text-sm text-slate-500">Loading resource data…</p>
      )}

      {result && result.configurations.length === 0 && (
        <p className="text-sm text-slate-500">
          No evaluated configuration matches this profile's tasks yet in this session.
        </p>
      )}

      {result && result.configurations.length > 0 && (
        <>
          <ResourceTable configurations={result.configurations} onOpenDrillDown={setDrillDown} />

          <ResourceConstraintForm
            constraints={constraints}
            onChange={setConstraints}
            availableMetrics={availableConstraintMetrics}
          />
          <QualificationTable configurations={result.configurations} />

          <ResourceComparisonSection
            configurations={result.configurations}
            comparison={result.resource_comparison}
            onCompare={setResourceComparison}
          />

          <ResourceParetoSection
            configurations={result.configurations}
            paretoFrontIds={result.pareto_front_configuration_ids}
            dimensions={dimensions}
            onChangeDimensions={setDimensions}
            availableDims={availableDims}
          />
        </>
      )}

      {drillDown && <ResourceMetricDrillDown sessionId={sessionId} target={drillDown} onClose={() => setDrillDown(null)} />}
    </div>
  );
}
