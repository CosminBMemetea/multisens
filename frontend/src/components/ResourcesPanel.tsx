import { useEffect, useState } from "react";
import { fetchSessionResourceObservations, fetchSessions, runTradeoffs } from "../api";
import { formatFractionPercent, formatResourceValue } from "../format";
import { PolicyStatusBadge } from "./PolicyStatusBadge";
import { ResourceQualityBadge } from "./ResourceQualityBadge";
import { ResourceTimeSeriesChart } from "./ResourceTimeSeriesChart";
import {
  RESOURCE_METRIC_LABELS,
  SUPPORTED_RESOURCE_METRICS,
} from "../types";
import type {
  ConfigurationTradeoff,
  DecisionPolicy,
  ResourceMetric,
  ResourceMetricSummary,
  ResourceObservation,
  Session,
  TradeoffResponse,
} from "../types";

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

function useTradeoffs(profileId: string, sessionId: string) {
  const [result, setResult] = useState<TradeoffResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

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
      resource_metrics: [...SUPPORTED_RESOURCE_METRICS],
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
  }, [profileId, sessionId]);

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

export function ResourcesPanel({ profileId, synthetic }: ResourcesPanelProps) {
  const sessions = useSessions();
  const [sessionId, setSessionId] = useState("");
  const { result, error } = useTradeoffs(profileId, sessionId);
  const [drillDown, setDrillDown] = useState<DrillDownTarget | null>(null);

  useEffect(() => {
    if (sessions && sessions.length > 0 && sessionId === "") setSessionId(sessions[0].id);
  }, [sessions, sessionId]);

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
        <ResourceTable configurations={result.configurations} onOpenDrillDown={setDrillDown} />
      )}

      {drillDown && <ResourceMetricDrillDown sessionId={sessionId} target={drillDown} onClose={() => setDrillDown(null)} />}
    </div>
  );
}
