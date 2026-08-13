import { useEffect, useMemo, useState } from "react";
import { ConditionFacetFilters } from "./ConditionFacetFilters";
import { RequirementDrillDown } from "./RequirementDrillDown";
import { StatusBadge } from "./StatusBadge";
import { fetchProfileFacets } from "../api";
import { useAnalysis } from "../hooks/useAnalysis";
import { formatCoverage, formatFractionPercent } from "../format";
import type { ConditionValue, Facet, GroupCoverage, Requirement, RequirementResult } from "../types";

interface FailuresPanelProps {
  profileId: string;
  requirements: Requirement[];
  conditionParams: Record<string, string>;
  onConditionChange: (key: string, rawValue: string | null) => void;
}

function flattenFailingGroups(root: GroupCoverage): GroupCoverage[] {
  const flat: GroupCoverage[] = [];
  function walk(node: GroupCoverage) {
    // group_id === null is the synthetic aggregation root, not a real
    // named group from the profile - never listed as a "failing group"
    // in its own right, same exclusion CoverageMatrix.tsx applies.
    if (node.group_id !== null && node.fail_count > 0) flat.push(node);
    node.children.forEach(walk);
  }
  walk(root);
  return flat.sort((a, b) => b.fail_count - a.fail_count);
}

// A requirement's evidence quality (matched samples, coverage) is shown
// directly alongside its StatusBadge, always, for every list row - never
// a derived "LIMITED EVIDENCE" badge or threshold (explicitly rejected in
// the v0.5 architecture review, Q2). A PASS with few samples must remain
// visibly a PASS, just with its raw numbers visible next to it.
function EvidenceQuality({ result }: { result: RequirementResult }) {
  if (!result.evidence) return <span className="text-xs text-slate-600">No evidence selected</span>;
  return (
    <span className="font-mono-data text-xs text-slate-500">
      {formatCoverage(result.evidence.matched_samples, result.evidence.sample_count)} coverage ·{" "}
      {result.evidence.matched_samples}/{result.evidence.sample_count} samples
    </span>
  );
}

export function FailuresPanel({ profileId, requirements, conditionParams, onConditionChange }: FailuresPanelProps) {
  const [facets, setFacets] = useState<Facet[] | null>(null);
  const [facetsError, setFacetsError] = useState<string | null>(null);
  const [configId, setConfigId] = useState("");
  const [drillDown, setDrillDown] = useState<{ requirement: Requirement; result: RequirementResult } | null>(null);

  const requirementsById = useMemo(() => new Map(requirements.map((r) => [r.id, r])), [requirements]);

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

  // Always scoped to fail status - that's this tab's entire purpose,
  // independent of whatever status the Explorer tab's own filter is set
  // to (the two tabs share condition filters, not the status filter).
  const { configurations, error: analysisError } = useAnalysis(profileId, conditions, "fail");

  useEffect(() => {
    if (configurations && configurations.length > 0 && configId === "") {
      setConfigId(configurations[0].configuration_id);
    }
  }, [configurations, configId]);

  const configuration = configurations?.find((c) => c.configuration_id === configId);
  const topFailingGroups = configuration ? flattenFailingGroups(configuration.failure_root) : [];

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

      {configurations === null && !analysisError && <p className="text-sm text-slate-500">Loading failures…</p>}

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

          {configuration && (
            <p className="text-sm text-slate-300">
              <span className="font-mono-data text-red-400">{configuration.summary.fail_count}</span> failing
              requirement{configuration.summary.fail_count === 1 ? "" : "s"} under current filters for{" "}
              <span className="font-mono-data">{configuration.configuration_id}</span>
            </p>
          )}

          {configuration && topFailingGroups.length > 0 && (
            <section className="flex flex-col gap-2">
              <h2 className="text-xs font-semibold uppercase tracking-wide text-slate-500">Top failing groups</h2>
              <ul className="flex flex-col gap-1">
                {topFailingGroups.map((g) => (
                  <li
                    key={g.group_id ?? "root"}
                    className="flex items-center justify-between gap-3 rounded border border-slate-800 bg-slate-950/40 px-3 py-2 text-sm"
                  >
                    <span className="text-slate-200">{g.name}</span>
                    <span className="font-mono-data text-xs text-slate-400">
                      {g.pass_count} pass / <span className="text-red-400">{g.fail_count} fail</span> / {g.na_count}{" "}
                      n/a · {formatFractionPercent(g.requirement_coverage)} coverage
                    </span>
                  </li>
                ))}
              </ul>
            </section>
          )}

          {configuration && (
            <section className="flex flex-col gap-2">
              <h2 className="text-xs font-semibold uppercase tracking-wide text-slate-500">Failing requirements</h2>
              {configuration.requirement_results.length === 0 ? (
                <p className="text-sm text-slate-500">No failures under current filters.</p>
              ) : (
                <ul className="flex flex-col gap-1">
                  {configuration.requirement_results.map((result) => {
                    const requirement = requirementsById.get(result.requirement_id);
                    if (!requirement) return null;
                    return (
                      <li key={result.requirement_id}>
                        <button
                          onClick={() => setDrillDown({ requirement, result })}
                          className="flex w-full items-center justify-between gap-3 rounded border border-slate-800 bg-slate-950/40 px-3 py-2 text-left text-sm hover:border-cyan-500/40"
                        >
                          <span className="flex flex-col gap-0.5">
                            <span className="text-slate-200">
                              {requirement.name}{" "}
                              <span className="font-mono-data text-xs text-slate-500">{requirement.task}</span>
                            </span>
                            <EvidenceQuality result={result} />
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
          requirement={drillDown.requirement}
          result={drillDown.result}
          onClose={() => setDrillDown(null)}
        />
      )}
    </div>
  );
}
