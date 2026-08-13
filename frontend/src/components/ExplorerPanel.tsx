import { useEffect, useMemo, useState } from "react";
import { fetchProfileFacets, runProfileAnalysis } from "../api";
import { formatFractionPercent } from "../format";
import type { AnalysisFilter, ConditionValue, ConfigurationAnalysis, Facet, RequirementStatus } from "../types";

const STATUS_OPTIONS: { value: RequirementStatus; label: string }[] = [
  { value: "pass", label: "PASS" },
  { value: "fail", label: "FAIL" },
  { value: "na", label: "N/A" },
];

interface ExplorerPanelProps {
  profileId: string;
  // Raw string values straight from useSearchParams, keyed by facet key -
  // resolved back to their originally-typed ConditionValue below once the
  // real facets are known (a boolean true and the string "true" are
  // different conditions to /analysis's type-sensitive filter match).
  conditionParams: Record<string, string>;
  status: RequirementStatus | null;
  onConditionChange: (key: string, rawValue: string | null) => void;
  onStatusChange: (status: RequirementStatus | null) => void;
}

export function ExplorerPanel({
  profileId,
  conditionParams,
  status,
  onConditionChange,
  onStatusChange,
}: ExplorerPanelProps) {
  const [facets, setFacets] = useState<Facet[] | null>(null);
  const [facetsError, setFacetsError] = useState<string | null>(null);
  const [configurations, setConfigurations] = useState<ConfigurationAnalysis[] | null>(null);
  const [analysisError, setAnalysisError] = useState<string | null>(null);

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

  // A stable string key for the effect below - fetch once per distinct
  // filter combination, not once per render (conditionParams is a fresh
  // object every render since it's carved out of useSearchParams).
  const filterKey = JSON.stringify({ conditions, status });

  useEffect(() => {
    let cancelled = false;
    setAnalysisError(null);
    const filters: AnalysisFilter = { conditions, status: status ?? undefined };
    runProfileAnalysis(profileId, { filters, group_by: [] })
      .then((result) => {
        if (!cancelled) setConfigurations(result.configurations);
      })
      .catch((err) => {
        if (!cancelled) setAnalysisError(String(err));
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [profileId, filterKey]);

  return (
    <div className="flex flex-col gap-4">
      {facetsError && (
        <div className="rounded border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-400">{facetsError}</div>
      )}

      <div className="flex flex-wrap items-end gap-4 rounded border border-slate-800 bg-slate-900/40 p-4">
        {facets && facets.length === 0 && (
          <p className="text-sm text-slate-500">This profile's requirements declare no conditions to filter by.</p>
        )}
        {facets?.map((facet) => (
          <label key={facet.key} className="flex flex-col gap-1 text-sm text-slate-400">
            {facet.key}
            <select
              value={conditionParams[facet.key] ?? ""}
              onChange={(e) => onConditionChange(facet.key, e.target.value || null)}
              className="rounded border border-slate-700 bg-slate-950 px-2 py-1.5 text-slate-100 focus:border-cyan-500/50 focus:outline-none"
            >
              <option value="">Any</option>
              {facet.values.map((v) => (
                <option key={String(v.value)} value={String(v.value)}>
                  {String(v.value)} ({v.requirement_count})
                </option>
              ))}
            </select>
          </label>
        ))}

        <label className="flex flex-col gap-1 text-sm text-slate-400">
          Status
          <select
            value={status ?? ""}
            onChange={(e) => onStatusChange((e.target.value || null) as RequirementStatus | null)}
            className="rounded border border-slate-700 bg-slate-950 px-2 py-1.5 text-slate-100 focus:border-cyan-500/50 focus:outline-none"
          >
            <option value="">Any</option>
            {STATUS_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>
        </label>
      </div>

      {analysisError && (
        <div className="rounded border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-400">{analysisError}</div>
      )}

      {configurations === null && !analysisError && (
        <p className="text-sm text-slate-500">Loading configuration summary…</p>
      )}

      {configurations && configurations.length === 0 && (
        <p className="text-sm text-slate-500">
          No evaluated configuration matches this profile's tasks yet - run evaluation on a session first.
        </p>
      )}

      {configurations && configurations.length > 0 && (
        <div className="overflow-x-auto rounded border border-slate-800">
          <table className="w-full text-left text-sm">
            <thead className="border-b border-slate-800 bg-slate-900/60 text-xs uppercase tracking-wide text-slate-500">
              <tr>
                <th className="px-3 py-2 font-medium">Configuration</th>
                <th className="px-3 py-2 font-medium">Pass</th>
                <th className="px-3 py-2 font-medium">Fail</th>
                <th className="px-3 py-2 font-medium">N/A</th>
                <th className="px-3 py-2 font-medium">Coverage</th>
                <th className="px-3 py-2 font-medium">Completeness</th>
              </tr>
            </thead>
            <tbody>
              {configurations.map((c) => (
                <tr key={c.configuration_id} className="border-b border-slate-800/60 last:border-0">
                  <td className="px-3 py-2 font-mono-data text-slate-200">{c.configuration_id}</td>
                  <td className="px-3 py-2 font-mono-data text-emerald-400">{c.summary.pass_count}</td>
                  <td className="px-3 py-2 font-mono-data text-red-400">{c.summary.fail_count}</td>
                  <td className="px-3 py-2 font-mono-data text-slate-400">{c.summary.na_count}</td>
                  <td className="px-3 py-2 font-mono-data text-slate-200">
                    {formatFractionPercent(c.summary.requirement_coverage)}
                  </td>
                  <td className="px-3 py-2 font-mono-data text-slate-200">
                    {formatFractionPercent(c.summary.evidence_completeness)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
