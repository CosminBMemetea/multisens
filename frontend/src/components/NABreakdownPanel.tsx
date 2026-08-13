import { useEffect, useMemo, useState } from "react";
import { ConditionFacetFilters } from "./ConditionFacetFilters";
import { RequirementDrillDown } from "./RequirementDrillDown";
import { StatusBadge } from "./StatusBadge";
import { fetchProfileFacets } from "../api";
import { useAnalysis } from "../hooks/useAnalysis";
import type { ConditionValue, Facet, Requirement, RequirementGroup, RequirementResult } from "../types";

interface NABreakdownPanelProps {
  profileId: string;
  profileName: string;
  profileVersion: string;
  requirements: Requirement[];
  groups: RequirementGroup[];
  conditionParams: Record<string, string>;
  onConditionChange: (key: string, rawValue: string | null) => void;
}

// classify_na_reason's categories, labeled here only for display - the
// classification itself is entirely backend-computed (na_breakdown on the
// /analysis response), never reimplemented client-side. The grouping
// below is the one distinction the v0.5 master prompt calls out
// explicitly: "no matching evidence" means the experiment was never run
// for this condition at all, while every other category means the
// experiment ran but the evaluation itself has a gap (ambiguous evidence,
// a metric that couldn't be computed). Conflating the two would hide a
// real gap behind "we just haven't tested that yet."
const NA_CATEGORY_LABELS: Record<string, string> = {
  no_matching_evidence: "No matching evidence",
  ambiguous_evidence: "Ambiguous evidence",
  missing_metric: "Missing metric",
  other: "Other",
};
const NO_EXPERIMENT_CATEGORIES = new Set(["no_matching_evidence"]);

export function NABreakdownPanel({
  profileId,
  profileName,
  profileVersion,
  requirements,
  groups,
  conditionParams,
  onConditionChange,
}: NABreakdownPanelProps) {
  const [facets, setFacets] = useState<Facet[] | null>(null);
  const [facetsError, setFacetsError] = useState<string | null>(null);
  const [configId, setConfigId] = useState("");
  const [drillDown, setDrillDown] = useState<
    { requirement: Requirement; result: RequirementResult; groupName: string | undefined } | null
  >(null);

  const requirementsById = useMemo(() => new Map(requirements.map((r) => [r.id, r])), [requirements]);
  const groupsById = useMemo(() => new Map(groups.map((g) => [g.id, g])), [groups]);

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

  const { configurations, error: analysisError } = useAnalysis(profileId, conditions, "na");

  useEffect(() => {
    if (configurations && configurations.length > 0 && configId === "") {
      setConfigId(configurations[0].configuration_id);
    }
  }, [configurations, configId]);

  const configuration = configurations?.find((c) => c.configuration_id === configId);
  const naBreakdown = configuration?.na_breakdown ?? {};
  const noExperimentCategories = Object.entries(naBreakdown).filter(([cat]) => NO_EXPERIMENT_CATEGORIES.has(cat));
  const evaluationGapCategories = Object.entries(naBreakdown).filter(([cat]) => !NO_EXPERIMENT_CATEGORIES.has(cat));

  return (
    <div className="flex flex-col gap-4">
      {facetsError && (
        <div className="rounded border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-400">{facetsError}</div>
      )}

      <div className="flex flex-wrap items-end gap-4 rounded border border-slate-800 bg-slate-900/40 p-4">
        <ConditionFacetFilters facets={facets} conditionParams={conditionParams} onConditionChange={onConditionChange} />
      </div>

      {analysisError && (
        <div className="rounded border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-400">{analysisError}</div>
      )}

      {configurations === null && !analysisError && <p className="text-sm text-slate-500">Loading N/A breakdown…</p>}

      {configurations && configurations.length === 0 && (
        <p className="text-sm text-slate-500">
          No evaluated configuration matches this profile's tasks yet - run evaluation on a session first.
        </p>
      )}

      {configurations && configurations.length > 0 && (
        <>
          <label className="flex w-fit flex-col gap-1 text-sm text-slate-400">
            Configuration
            <select
              value={configId}
              onChange={(e) => setConfigId(e.target.value)}
              className="rounded border border-slate-700 bg-slate-950 px-2 py-1.5 text-slate-100 focus:border-cyan-500/50 focus:outline-none"
            >
              {configurations.map((c) => (
                <option key={c.configuration_id} value={c.configuration_id}>
                  {c.configuration_id}
                </option>
              ))}
            </select>
          </label>

          {configuration && Object.keys(naBreakdown).length === 0 && (
            <p className="text-sm text-slate-500">No N/A requirements under current filters.</p>
          )}

          {configuration && Object.keys(naBreakdown).length > 0 && (
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
              {noExperimentCategories.length > 0 && (
                <section className="flex flex-col gap-2 rounded border border-slate-800 bg-slate-900/40 p-3">
                  <h2 className="text-xs font-semibold uppercase tracking-wide text-slate-500">
                    Experiment never performed
                  </h2>
                  <ul className="flex flex-col gap-1 text-sm">
                    {noExperimentCategories.map(([cat, count]) => (
                      <li key={cat} className="flex items-center justify-between">
                        <span className="text-slate-300">{NA_CATEGORY_LABELS[cat] ?? cat}</span>
                        <span className="font-mono-data text-slate-400">{count}</span>
                      </li>
                    ))}
                  </ul>
                </section>
              )}
              {evaluationGapCategories.length > 0 && (
                <section className="flex flex-col gap-2 rounded border border-amber-500/30 bg-amber-500/5 p-3">
                  <h2 className="text-xs font-semibold uppercase tracking-wide text-amber-400">
                    Evaluation gap - not a missing experiment
                  </h2>
                  <ul className="flex flex-col gap-1 text-sm">
                    {evaluationGapCategories.map(([cat, count]) => (
                      <li key={cat} className="flex items-center justify-between">
                        <span className="text-slate-300">{NA_CATEGORY_LABELS[cat] ?? cat}</span>
                        <span className="font-mono-data text-slate-400">{count}</span>
                      </li>
                    ))}
                  </ul>
                </section>
              )}
            </div>
          )}

          {configuration && (
            <section className="flex flex-col gap-2">
              <h2 className="text-xs font-semibold uppercase tracking-wide text-slate-500">N/A requirements</h2>
              {configuration.requirement_results.length === 0 ? (
                <p className="text-sm text-slate-500">No N/A requirements under current filters.</p>
              ) : (
                <ul className="flex flex-col gap-1">
                  {configuration.requirement_results.map((result) => {
                    const requirement = requirementsById.get(result.requirement_id);
                    if (!requirement) return null;
                    return (
                      <li key={result.requirement_id}>
                        <button
                          onClick={() =>
                            setDrillDown({ requirement, result, groupName: groupsById.get(requirement.group_id)?.name })
                          }
                          className="flex w-full items-center justify-between gap-3 rounded border border-slate-800 bg-slate-950/40 px-3 py-2 text-left text-sm hover:border-cyan-500/40"
                        >
                          <span className="flex flex-col gap-0.5">
                            <span className="text-slate-200">
                              {requirement.name}{" "}
                              <span className="font-mono-data text-xs text-slate-500">{requirement.task}</span>
                            </span>
                            {result.reasons.length > 0 && (
                              <span className="text-xs text-slate-500">{result.reasons[0]}</span>
                            )}
                          </span>
                          <StatusBadge status={result.status} />
                        </button>
                      </li>
                    );
                  })}
                </ul>
              )}
            </section>
          )}
        </>
      )}

      {drillDown && (
        <RequirementDrillDown
          profileName={profileName}
          profileVersion={profileVersion}
          groupName={drillDown.groupName}
          requirement={drillDown.requirement}
          result={drillDown.result}
          onClose={() => setDrillDown(null)}
        />
      )}
    </div>
  );
}
