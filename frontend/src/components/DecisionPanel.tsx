import { useEffect, useMemo, useState } from "react";
import { CellDrillDown } from "./CellDrillDown";
import { ConditionFacetFilters } from "./ConditionFacetFilters";
import { PolicyStatusBadge } from "./PolicyStatusBadge";
import { SourceTypeBadge } from "./Badge";
import { fetchProfileFacets, fetchSensors, runDecisionAnalysis } from "../api";
import { formatDeltaPp, formatFractionPercent } from "../format";
import type {
  AggregateCoverage,
  ConditionValue,
  ConfigurationDecision,
  DecisionAnalysisResponse,
  DecisionPolicy,
  Facet,
  GapAnalysisResult,
  Requirement,
  RequirementGroup,
  RequirementResult,
  RequirementTransitions,
  SensorConfig,
} from "../types";

interface DecisionPanelProps {
  profileId: string;
  profileName: string;
  profileVersion: string;
  requirements: Requirement[];
  groups: RequirementGroup[];
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

// Checked directly against the active policy's own criteria - not a
// separate "why" computation, so this can never drift from what
// policy_status itself already decided.
function WhySufficientChecklist({ policy, aggregate }: { policy: DecisionPolicy; aggregate: AggregateCoverage }) {
  const items: { met: boolean; label: string }[] = [
    {
      met: aggregate.requirement_coverage !== null && aggregate.requirement_coverage >= policy.minimum_requirement_coverage,
      label: `Coverage ${formatFractionPercent(aggregate.requirement_coverage)} ≥ ${formatFractionPercent(policy.minimum_requirement_coverage)}`,
    },
    {
      met:
        aggregate.evidence_completeness !== null &&
        aggregate.evidence_completeness >= policy.minimum_evidence_completeness,
      label: `Completeness ${formatFractionPercent(aggregate.evidence_completeness)} ≥ ${formatFractionPercent(policy.minimum_evidence_completeness)}`,
    },
  ];
  if (policy.mandatory_requirements_must_pass) {
    items.push({
      met: aggregate.fail_count === 0 && aggregate.na_count === 0,
      label: "All requirements pass (mandatory)",
    });
  }
  return (
    <ul className="mt-2 flex flex-col gap-0.5 font-mono-data text-xs">
      {items.map((item) => (
        <li key={item.label} className={item.met ? "text-emerald-400" : "text-red-400"}>
          {item.met ? "✓" : "✗"} {item.label}
        </li>
      ))}
    </ul>
  );
}

// One card per minimal sufficient configuration - several may tie, all
// shown, never arbitrarily narrowed to one (v0.6 master prompt §9/§32).
function MinimalSufficientSets({
  result, policy, sensorsById,
}: {
  result: DecisionAnalysisResponse; policy: DecisionPolicy; sensorsById: Record<string, SensorConfig>;
}) {
  const byId = new Map(result.configurations.map((c) => [c.configuration_id, c]));
  const minimal = result.minimal_sufficient_configuration_ids
    .map((id) => byId.get(id))
    .filter((c): c is ConfigurationDecision => c !== undefined);

  return (
    <section className="flex flex-col gap-3">
      <h2 className="text-xs font-semibold uppercase tracking-wide text-slate-500">
        Minimum sufficient configurations
      </h2>
      {minimal.length === 0 ? (
        <p className="text-sm text-slate-500">No configuration is sufficient under the current policy.</p>
      ) : (
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          {minimal.map((c) => (
            <div key={c.configuration_id} className="rounded border border-emerald-500/30 bg-emerald-500/5 p-3">
              <div className="flex items-center justify-between gap-2">
                <span className="font-mono-data text-sm text-slate-200">{c.configuration_id}</span>
                <span className="font-mono-data text-xs text-slate-500">
                  {c.sensor_count} sensor{c.sensor_count === 1 ? "" : "s"}
                </span>
              </div>
              <div className="mt-1.5">
                <SensorChips sensorIds={c.sensor_ids} sensorsById={sensorsById} />
              </div>
              <WhySufficientChecklist policy={policy} aggregate={c.summary} />
            </div>
          ))}
        </div>
      )}
      {minimal.length > 1 && (
        <p className="text-xs text-slate-600">
          {minimal.length} configurations tie for minimum sufficient under this policy - shown unranked, not one
          picked arbitrarily.
        </p>
      )}
    </section>
  );
}

// Non-dominated configurations shown prominently; dominated ones
// collapsed below, visually flagged DOMINATED - never "bad" (v0.6
// master prompt §18/§37). No configuration-graph visualization - a
// table carries the same information at far lower cost (v0.6
// architecture review, "what I'd remove").
function ParetoFront({ result }: { result: DecisionAnalysisResponse }) {
  // Only configurations that actually entered dominance computation -
  // a NO EVIDENCE row (policy_status: null) was never evaluated for
  // sensor_count/coverage trade-offs at all.
  const evaluated = result.configurations.filter((c) => c.policy_status !== null);
  const nonDominated = evaluated.filter((c) => !c.dominated).sort((a, b) => a.sensor_count - b.sensor_count);
  const dominated = evaluated.filter((c) => c.dominated).sort((a, b) => a.sensor_count - b.sensor_count);

  if (evaluated.length === 0) return null;

  return (
    <section className="flex flex-col gap-3">
      <h2 className="text-xs font-semibold uppercase tracking-wide text-slate-500">Pareto front</h2>
      <div className="overflow-x-auto rounded border border-slate-800">
        <table className="w-full text-left text-sm">
          <thead className="border-b border-slate-800 bg-slate-900/60 text-xs uppercase tracking-wide text-slate-500">
            <tr>
              <th className="px-3 py-2 font-medium">Sensors</th>
              <th className="px-3 py-2 font-medium">Coverage</th>
              <th className="px-3 py-2 font-medium">Completeness</th>
              <th className="px-3 py-2 font-medium">Configuration</th>
              <th className="px-3 py-2 font-medium">Policy status</th>
            </tr>
          </thead>
          <tbody>
            {nonDominated.map((c) => (
              <tr key={c.configuration_id} className="border-b border-slate-800/60 last:border-0">
                <td className="px-3 py-2 font-mono-data text-slate-200">{c.sensor_count}</td>
                <td className="px-3 py-2 font-mono-data text-slate-200">
                  {formatFractionPercent(c.summary.requirement_coverage)}
                </td>
                <td className="px-3 py-2 font-mono-data text-slate-200">
                  {formatFractionPercent(c.summary.evidence_completeness)}
                </td>
                <td className="px-3 py-2 font-mono-data text-slate-200">{c.configuration_id}</td>
                <td className="px-3 py-2">
                  <PolicyStatusBadge status={c.policy_status} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {dominated.length > 0 && (
        <details className="rounded border border-slate-800">
          <summary className="cursor-pointer select-none px-3 py-2 text-xs font-semibold uppercase tracking-wide text-slate-500">
            {dominated.length} dominated configuration{dominated.length === 1 ? "" : "s"}
          </summary>
          <table className="w-full text-left text-sm">
            <tbody>
              {dominated.map((c) => (
                <tr key={c.configuration_id} className="border-t border-slate-800/60">
                  <td className="px-3 py-2 font-mono-data text-slate-400">{c.sensor_count}</td>
                  <td className="px-3 py-2 font-mono-data text-slate-400">
                    {formatFractionPercent(c.summary.requirement_coverage)}
                  </td>
                  <td className="px-3 py-2 font-mono-data text-slate-400">
                    {formatFractionPercent(c.summary.evidence_completeness)}
                  </td>
                  <td className="px-3 py-2 font-mono-data text-slate-400">{c.configuration_id}</td>
                  <td className="px-3 py-2">
                    <span className="inline-flex items-center justify-center rounded border border-slate-700 bg-slate-950 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-slate-500">
                      Dominated
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </details>
      )}
    </section>
  );
}

interface CellMatch {
  requirement: Requirement;
  result: RequirementResult;
  groupName: string | undefined;
}

const TRANSITION_LABELS: Record<keyof RequirementTransitions, string> = {
  fail_to_pass: "Newly passed (was failing)",
  na_to_pass: "N/A resolved to pass",
  pass_to_fail: "Regressed to fail",
  pass_to_na: "Regressed to N/A",
};

function removalStatusCopy(status: "sufficient" | "insufficient" | "undetermined" | null): string {
  // Scoped wording only - "removable without violating the current
  // policy" / "policy-critical within this configuration" - never
  // "redundant sensor" or "necessary sensor" as an intrinsic property
  // (v0.6 master prompt §11/§12).
  if (status === null) return "No evaluated configuration exists for this removal";
  if (status === "sufficient") return "Removable without violating the current policy";
  if (status === "insufficient") return "Policy-critical within this configuration";
  return "Removal evaluated, but not enough evidence to say either way";
}

// Baseline/candidate comparison plus an optional sensor-removal sweep -
// a separate fetch from the main summary above (its own request shape,
// only needed once a specific pair/baseline is picked), matching the
// same "one fetch per distinct interaction, not per unrelated UI event"
// boundary the Explorer tab's breakdown/cross-tab sections already
// established.
function GapAnalysisSection({
  profileId, profileName, profileVersion, requirements, groups, policy, conditions, configurations,
}: {
  profileId: string;
  profileName: string;
  profileVersion: string;
  requirements: Requirement[];
  groups: RequirementGroup[];
  policy: DecisionPolicy;
  conditions: Record<string, ConditionValue>;
  configurations: ConfigurationDecision[];
}) {
  const evaluatedConfigs = useMemo(() => configurations.filter((c) => c.policy_status !== null), [configurations]);
  const [baselineId, setBaselineId] = useState("");
  const [candidateId, setCandidateId] = useState("");
  const [includeRemovalSweep, setIncludeRemovalSweep] = useState(true);
  const [gapResult, setGapResult] = useState<GapAnalysisResult | null>(null);
  const [gapError, setGapError] = useState<string | null>(null);
  const [drillDown, setDrillDown] = useState<{ label: string; matches: CellMatch[] } | null>(null);

  useEffect(() => {
    if (evaluatedConfigs.length > 0 && baselineId === "") setBaselineId(evaluatedConfigs[0].configuration_id);
  }, [evaluatedConfigs, baselineId]);

  const requirementsById = useMemo(() => new Map(requirements.map((r) => [r.id, r])), [requirements]);
  const groupsById = useMemo(() => new Map(groups.map((g) => [g.id, g])), [groups]);
  // Same condition dimensions ConditionFacetFilters discovers elsewhere
  // on this page - derived independently here (cheap, same source data)
  // rather than threaded as a prop.
  const groupByDims = useMemo(
    () => [...new Set(requirements.flatMap((r) => Object.keys(r.conditions)))].sort(),
    [requirements],
  );

  const key = JSON.stringify({ policy, conditions, baselineId, candidateId, includeRemovalSweep, groupByDims });
  useEffect(() => {
    if (baselineId === "") {
      setGapResult(null);
      return;
    }
    let cancelled = false;
    setGapError(null);
    runDecisionAnalysis(profileId, {
      policy,
      filters: { conditions },
      gap_analysis: {
        baseline_configuration_id: baselineId,
        candidate_configuration_id: candidateId || undefined,
        include_removal_sweep: includeRemovalSweep,
        group_by: groupByDims,
      },
    })
      .then((r) => {
        if (!cancelled) setGapResult(r.gap_analysis);
      })
      .catch((err) => {
        if (!cancelled) setGapError(String(err));
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [profileId, key]);

  function openTransitionDrillDown(label: string, requirementIds: string[]) {
    const candidateConfig = configurations.find((c) => c.configuration_id === candidateId);
    if (!candidateConfig) return;
    const resultsById = new Map(candidateConfig.requirement_results.map((r) => [r.requirement_id, r]));
    const matches: CellMatch[] = [];
    for (const id of requirementIds) {
      const requirement = requirementsById.get(id);
      const result = resultsById.get(id);
      if (requirement && result) {
        matches.push({ requirement, result, groupName: groupsById.get(requirement.group_id)?.name });
      }
    }
    setDrillDown({ label, matches });
  }

  const inputClass =
    "rounded border border-slate-700 bg-slate-950 px-2 py-1.5 text-slate-100 focus:border-cyan-500/50 focus:outline-none";

  return (
    <section className="flex flex-col gap-3">
      <h2 className="text-xs font-semibold uppercase tracking-wide text-slate-500">Gap &amp; redundancy analysis</h2>

      <div className="flex flex-wrap items-end gap-4 rounded border border-slate-800 bg-slate-900/40 p-4">
        <label className="flex flex-col gap-1 text-sm text-slate-400">
          Baseline
          <select value={baselineId} onChange={(e) => setBaselineId(e.target.value)} className={inputClass}>
            {evaluatedConfigs.map((c) => (
              <option key={c.configuration_id} value={c.configuration_id}>
                {c.configuration_id}
              </option>
            ))}
          </select>
        </label>
        <label className="flex flex-col gap-1 text-sm text-slate-400">
          Candidate (optional)
          <select value={candidateId} onChange={(e) => setCandidateId(e.target.value)} className={inputClass}>
            <option value="">None</option>
            {evaluatedConfigs
              .filter((c) => c.configuration_id !== baselineId)
              .map((c) => (
                <option key={c.configuration_id} value={c.configuration_id}>
                  {c.configuration_id}
                </option>
              ))}
          </select>
        </label>
        <label className="flex items-center gap-2 text-sm text-slate-400">
          <input
            type="checkbox"
            checked={includeRemovalSweep}
            onChange={(e) => setIncludeRemovalSweep(e.target.checked)}
          />
          Sensor removal sweep for baseline
        </label>
      </div>

      {gapError && (
        <div className="rounded border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-400">{gapError}</div>
      )}

      {gapResult?.addition && (
        <div className="flex flex-col gap-3 rounded border border-slate-800 bg-slate-900/40 p-4">
          <p className="text-sm text-slate-300">
            {gapResult.addition.added_sensor_ids.length > 0 && (
              <>
                Adding <span className="font-mono-data text-cyan-400">{gapResult.addition.added_sensor_ids.join(", ")}</span>{" "}
              </>
            )}
            {gapResult.addition.removed_sensor_ids.length > 0 && (
              <>
                removing <span className="font-mono-data text-amber-400">{gapResult.addition.removed_sensor_ids.join(", ")}</span>{" "}
              </>
            )}
            to go from <span className="font-mono-data">{gapResult.addition.baseline_configuration_id}</span> to{" "}
            <span className="font-mono-data">{gapResult.addition.candidate_configuration_id}</span>.
          </p>
          <div className="flex flex-wrap items-center gap-6 text-sm text-slate-400">
            <span>
              Coverage <span className="font-mono-data text-slate-200">{formatDeltaPp(gapResult.addition.coverage_delta_pp)}</span>
            </span>
            <span>
              Completeness{" "}
              <span className="font-mono-data text-slate-200">
                {formatDeltaPp(gapResult.addition.completeness_delta_pp)}
              </span>
            </span>
            <span className="flex items-center gap-1.5">
              Baseline <PolicyStatusBadge status={gapResult.addition.baseline_policy_status} />
            </span>
            <span className="flex items-center gap-1.5">
              Candidate <PolicyStatusBadge status={gapResult.addition.candidate_policy_status} />
            </span>
          </div>

          <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
            {(Object.keys(TRANSITION_LABELS) as (keyof RequirementTransitions)[]).map((transitionKey) => {
              const ids = gapResult.addition!.transitions[transitionKey];
              return (
                <button
                  key={transitionKey}
                  disabled={ids.length === 0}
                  onClick={() => openTransitionDrillDown(TRANSITION_LABELS[transitionKey], ids)}
                  className="flex flex-col items-start gap-0.5 rounded border border-slate-800 bg-slate-950/40 px-3 py-2 text-left disabled:opacity-40"
                >
                  <span className="font-mono-data text-lg text-slate-200">{ids.length}</span>
                  <span className="text-[11px] text-slate-500">{TRANSITION_LABELS[transitionKey]}</span>
                </button>
              );
            })}
          </div>

          {Object.keys(gapResult.addition.condition_gap_summaries).length > 0 && (
            <div className="flex flex-col gap-2">
              <h3 className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">
                Observed coverage difference under condition - not a causal claim
              </h3>
              {Object.entries(gapResult.addition.condition_gap_summaries).map(([dimension, entries]) => (
                <div key={dimension} className="flex flex-col gap-1">
                  <span className="font-mono-data text-xs text-slate-400">{dimension}</span>
                  <div className="flex flex-wrap gap-2">
                    {entries.map((entry) => (
                      <span
                        key={String(entry.value)}
                        title={`${entry.baseline.pass_count}/${entry.baseline.pass_count + entry.baseline.fail_count + entry.baseline.na_count} → ${entry.candidate.pass_count}/${entry.candidate.pass_count + entry.candidate.fail_count + entry.candidate.na_count}`}
                        className="rounded border border-slate-800 bg-slate-950/40 px-2 py-1 font-mono-data text-xs text-slate-300"
                      >
                        {String(entry.value)}: {formatDeltaPp(entry.coverage_delta_pp)}
                      </span>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {gapResult?.removal_sweep && (
        <div className="rounded border border-slate-800 bg-slate-900/40 p-4">
          <h3 className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-slate-500">
            Sensor removal analysis for {baselineId}
          </h3>
          <ul className="flex flex-col gap-1">
            {gapResult.removal_sweep.map((removal) => (
              <li
                key={removal.removed_sensor_id}
                className="flex items-center justify-between gap-3 rounded border border-slate-800 bg-slate-950/40 px-3 py-2 text-sm"
              >
                <span className="font-mono-data text-slate-200">{removal.removed_sensor_id}</span>
                <span className="text-xs text-slate-500">{removalStatusCopy(removal.policy_status)}</span>
                <PolicyStatusBadge status={removal.policy_status} />
              </li>
            ))}
          </ul>
        </div>
      )}

      {drillDown && (
        <CellDrillDown
          profileName={profileName}
          profileVersion={profileVersion}
          label={drillDown.label}
          matches={drillDown.matches}
          onClose={() => setDrillDown(null)}
        />
      )}
    </section>
  );
}

export function DecisionPanel({
  profileId, profileName, profileVersion, requirements, groups, conditionParams, onConditionChange,
}: DecisionPanelProps) {
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

      {result && result.configurations.length > 0 && (
        <>
          <MinimalSufficientSets result={result} policy={policy} sensorsById={sensorsById} />
          <ParetoFront result={result} />
          <GapAnalysisSection
            profileId={profileId}
            profileName={profileName}
            profileVersion={profileVersion}
            requirements={requirements}
            groups={groups}
            policy={policy}
            conditions={conditions}
            configurations={result.configurations}
          />
        </>
      )}
    </div>
  );
}
