import { useEffect, useMemo, useState } from "react";
import { ConditionFacetFilters } from "./ConditionFacetFilters";
import { PolicyStatusBadge } from "./PolicyStatusBadge";
import { SourceTypeBadge } from "./Badge";
import { fetchProfileFacets, fetchSensors, runDecisionAnalysis } from "../api";
import { formatFractionPercent } from "../format";
import type { ConditionValue, DecisionAnalysisResponse, DecisionPolicy, Facet, SensorConfig } from "../types";

interface DecisionPanelProps {
  profileId: string;
  conditionParams: Record<string, string>;
  onConditionChange: (key: string, rawValue: string | null) => void;
}

// A starting point only, always visible and editable in the form below -
// the API itself has no default of its own (DecisionPolicy has no
// optional field), so this is never silently applied. Coverage/
// completeness values deliberately not 100%/100% - a looser example is
// less likely to be mistaken for a regulatory-looking bar (v0.6
// architecture review, §29).
const DEMO_POLICY: DecisionPolicy = {
  minimum_requirement_coverage: 1.0,
  minimum_evidence_completeness: 0.95,
  mandatory_requirements_must_pass: false,
  objective: "minimize_sensor_count",
};

function useDecisionAnalysis(
  profileId: string,
  policy: DecisionPolicy,
  conditions: Record<string, ConditionValue>,
) {
  const [result, setResult] = useState<DecisionAnalysisResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const key = JSON.stringify({ policy, conditions });

  useEffect(() => {
    let cancelled = false;
    setError(null);
    runDecisionAnalysis(profileId, { policy, filters: { conditions } })
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
  }, [profileId, key]);

  return { result, error };
}

function PolicyForm({ policy, onChange }: { policy: DecisionPolicy; onChange: (policy: DecisionPolicy) => void }) {
  return (
    <div className="flex flex-wrap items-end gap-4 rounded border border-slate-800 bg-slate-900/40 p-4">
      <label className="flex flex-col gap-1 text-sm text-slate-400">
        Minimum coverage
        <input
          type="number"
          min={0}
          max={1}
          step={0.01}
          value={policy.minimum_requirement_coverage}
          onChange={(e) => onChange({ ...policy, minimum_requirement_coverage: Number(e.target.value) })}
          className="w-28 rounded border border-slate-700 bg-slate-950 px-2 py-1.5 text-slate-100 focus:border-cyan-500/50 focus:outline-none"
        />
      </label>
      <label className="flex flex-col gap-1 text-sm text-slate-400">
        Minimum completeness
        <input
          type="number"
          min={0}
          max={1}
          step={0.01}
          value={policy.minimum_evidence_completeness}
          onChange={(e) => onChange({ ...policy, minimum_evidence_completeness: Number(e.target.value) })}
          className="w-28 rounded border border-slate-700 bg-slate-950 px-2 py-1.5 text-slate-100 focus:border-cyan-500/50 focus:outline-none"
        />
      </label>
      <label className="flex items-center gap-2 text-sm text-slate-400">
        <input
          type="checkbox"
          checked={policy.mandatory_requirements_must_pass}
          onChange={(e) => onChange({ ...policy, mandatory_requirements_must_pass: e.target.checked })}
        />
        Mandatory requirements must pass
      </label>
      <label className="flex flex-col gap-1 text-sm text-slate-400">
        Objective
        {/* Only one value exists in v0.6 - shown, not hidden, but not
            editable either (see DecisionObjective's Literal type). */}
        <select
          value={policy.objective}
          disabled
          className="w-56 rounded border border-slate-700 bg-slate-950 px-2 py-1.5 text-slate-500"
        >
          <option value="minimize_sensor_count">Minimize sensor count</option>
        </select>
      </label>
    </div>
  );
}

function SensorChips({ sensorIds, sensorsById }: { sensorIds: string[]; sensorsById: Record<string, SensorConfig> }) {
  if (sensorIds.length === 0) return <span className="text-slate-700">—</span>;
  return (
    <div className="flex flex-wrap gap-1">
      {sensorIds.map((id) => (
        <span
          key={id}
          className="flex items-center gap-1 rounded border border-slate-700 bg-slate-950 px-1.5 py-0.5 font-mono-data text-[11px] text-slate-300"
        >
          {id}
          {sensorsById[id] && <SourceTypeBadge sourceType={sensorsById[id].source_type} />}
        </span>
      ))}
    </div>
  );
}

export function DecisionPanel({ profileId, conditionParams, onConditionChange }: DecisionPanelProps) {
  const [facets, setFacets] = useState<Facet[] | null>(null);
  const [facetsError, setFacetsError] = useState<string | null>(null);
  const [sensorsById, setSensorsById] = useState<Record<string, SensorConfig>>({});
  const [policy, setPolicy] = useState<DecisionPolicy>(DEMO_POLICY);

  useEffect(() => {
    let cancelled = false;
    fetchProfileFacets(profileId)
      .then((result) => {
        if (!cancelled) setFacets(result);
      })
      .catch((err) => {
        if (!cancelled) setFacetsError(String(err));
      });
    return () => {
      cancelled = true;
    };
  }, [profileId]);

  useEffect(() => {
    // Live sensors only (config/sensors.yaml-backed) - a sensor_id with
    // no matching entry (e.g. an evaluation-only id never wired to a
    // live source) just renders without a badge, not an error.
    fetchSensors()
      .then((sensors) => setSensorsById(Object.fromEntries(sensors.map((s) => [s.id, s]))))
      .catch(() => {});
  }, []);

  const conditions = useMemo<Record<string, ConditionValue>>(() => {
    if (!facets) return {};
    const resolved: Record<string, ConditionValue> = {};
    for (const facet of facets) {
      const raw = conditionParams[facet.key];
      if (raw === undefined) continue;
      const match = facet.values.find((v) => String(v.value) === raw);
      if (match) resolved[facet.key] = match.value;
    }
    return resolved;
  }, [facets, conditionParams]);

  const { result, error } = useDecisionAnalysis(profileId, policy, conditions);

  return (
    <div className="flex flex-col gap-4">
      {facetsError && (
        <div className="rounded border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-400">{facetsError}</div>
      )}

      <PolicyForm policy={policy} onChange={setPolicy} />

      <div className="flex flex-wrap items-end gap-4 rounded border border-slate-800 bg-slate-900/40 p-4">
        <ConditionFacetFilters facets={facets} conditionParams={conditionParams} onConditionChange={onConditionChange} />
      </div>

      {error && (
        <div className="rounded border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-400">{error}</div>
      )}

      {result === null && !error && <p className="text-sm text-slate-500">Loading decision analysis…</p>}

      {result && result.configurations.length === 0 && (
        <p className="text-sm text-slate-500">
          No evaluated configuration matches this profile's tasks yet - run evaluation on a session first.
        </p>
      )}

      {result && result.configurations.length > 0 && (
        <div className="overflow-x-auto rounded border border-slate-800">
          <table className="w-full text-left text-sm">
            <thead className="border-b border-slate-800 bg-slate-900/60 text-xs uppercase tracking-wide text-slate-500">
              <tr>
                <th className="px-3 py-2 font-medium">Configuration</th>
                <th className="px-3 py-2 font-medium">Sensors</th>
                <th className="px-3 py-2 font-medium">Coverage</th>
                <th className="px-3 py-2 font-medium">Completeness</th>
                <th className="px-3 py-2 font-medium">Policy status</th>
                <th className="px-3 py-2 font-medium">Dominated</th>
              </tr>
            </thead>
            <tbody>
              {result.configurations.map((c) => (
                <tr key={c.configuration_id} className="border-b border-slate-800/60 last:border-0">
                  <td className="px-3 py-2 font-mono-data text-slate-200">{c.configuration_id}</td>
                  <td className="px-3 py-2">
                    <SensorChips sensorIds={c.sensor_ids} sensorsById={sensorsById} />
                  </td>
                  <td className="px-3 py-2 font-mono-data text-slate-200">
                    {formatFractionPercent(c.summary.requirement_coverage)}
                  </td>
                  <td className="px-3 py-2 font-mono-data text-slate-200">
                    {formatFractionPercent(c.summary.evidence_completeness)}
                  </td>
                  <td className="px-3 py-2">
                    <PolicyStatusBadge status={c.policy_status} />
                  </td>
                  <td className="px-3 py-2 text-slate-400">{c.dominated ? "Yes" : "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
