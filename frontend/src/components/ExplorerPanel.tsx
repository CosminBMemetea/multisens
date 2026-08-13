import { useEffect, useMemo, useState } from "react";
import { CellDrillDown } from "./CellDrillDown";
import { ConditionCrossTab } from "./ConditionCrossTab";
import { ConditionFacetFilters } from "./ConditionFacetFilters";
import { fetchProfileFacets } from "../api";
import { useAnalysis } from "../hooks/useAnalysis";
import { formatFractionPercent } from "../format";
import type {
  ConditionValue,
  ConfigurationAnalysis,
  Facet,
  Requirement,
  RequirementGroup,
  RequirementResult,
  RequirementStatus,
} from "../types";

const STATUS_OPTIONS: { value: RequirementStatus; label: string }[] = [
  { value: "pass", label: "PASS" },
  { value: "fail", label: "FAIL" },
  { value: "na", label: "N/A" },
];

interface ExplorerPanelProps {
  profileId: string;
  profileName: string;
  profileVersion: string;
  requirements: Requirement[];
  groups: RequirementGroup[];
  // Raw string values straight from useSearchParams, keyed by facet key -
  // resolved back to their originally-typed ConditionValue below once the
  // real facets are known (a boolean true and the string "true" are
  // different conditions to /analysis's type-sensitive filter match).
  conditionParams: Record<string, string>;
  status: RequirementStatus | null;
  onConditionChange: (key: string, rawValue: string | null) => void;
  onStatusChange: (status: RequirementStatus | null) => void;
}

interface CellMatch {
  requirement: Requirement;
  result: RequirementResult;
  groupName: string | undefined;
}

function resolveFacetValue(facet: Facet | undefined, label: string): ConditionValue | undefined {
  return facet?.values.find((v) => String(v.value) === label)?.value;
}

function matchesForConfiguration(
  configuration: ConfigurationAnalysis,
  requirementsById: Map<string, Requirement>,
  groupsById: Map<string, RequirementGroup>,
  predicate: (requirement: Requirement) => boolean,
): CellMatch[] {
  const matches: CellMatch[] = [];
  for (const result of configuration.requirement_results) {
    const requirement = requirementsById.get(result.requirement_id);
    if (requirement && predicate(requirement)) {
      matches.push({ requirement, result, groupName: groupsById.get(requirement.group_id)?.name });
    }
  }
  return matches;
}

export function ExplorerPanel({
  profileId,
  profileName,
  profileVersion,
  requirements,
  groups,
  conditionParams,
  status,
  onConditionChange,
  onStatusChange,
}: ExplorerPanelProps) {
  const [facets, setFacets] = useState<Facet[] | null>(null);
  const [facetsError, setFacetsError] = useState<string | null>(null);
  const [drillDown, setDrillDown] = useState<{ label: string; matches: CellMatch[] } | null>(null);

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

  const { configurations, error: analysisError } = useAnalysis(profileId, conditions, status, []);

  // --- Per-condition breakdown: configuration x dimension-value grid ------

  const [breakdownDim, setBreakdownDim] = useState("");
  useEffect(() => {
    if (facets && facets.length > 0 && breakdownDim === "") setBreakdownDim(facets[0].key);
  }, [facets, breakdownDim]);

  const { configurations: breakdownConfigurations, error: breakdownError } = useAnalysis(
    profileId,
    conditions,
    status,
    breakdownDim ? [breakdownDim] : [],
  );

  const breakdownFacet = facets?.find((f) => f.key === breakdownDim);

  function handleBreakdownCellClick(row: string, col: string) {
    const configuration = breakdownConfigurations?.find((c) => c.configuration_id === row);
    const value = resolveFacetValue(breakdownFacet, col);
    if (!configuration || value === undefined) return;
    const matches = matchesForConfiguration(
      configuration,
      requirementsById,
      groupsById,
      (r) => r.conditions[breakdownDim] === value,
    );
    setDrillDown({ label: `${row} · ${breakdownDim}=${col}`, matches });
  }

  // --- 2D cross-tab: dimension x dimension grid, within one configuration -

  const [rowDim, setRowDim] = useState("");
  const [colDim, setColDim] = useState("");
  useEffect(() => {
    if (facets && facets.length > 0 && rowDim === "") setRowDim(facets[0].key);
    if (facets && facets.length > 1 && colDim === "") setColDim(facets[1].key);
  }, [facets, rowDim, colDim]);

  const columnDimOptions = useMemo(() => (facets ?? []).filter((f) => f.key !== rowDim), [facets, rowDim]);
  useEffect(() => {
    if (colDim === rowDim) setColDim(columnDimOptions[0]?.key ?? "");
  }, [rowDim, colDim, columnDimOptions]);

  const [crossTabConfigId, setCrossTabConfigId] = useState("");
  useEffect(() => {
    if (configurations && configurations.length > 0 && crossTabConfigId === "") {
      setCrossTabConfigId(configurations[0].configuration_id);
    }
  }, [configurations, crossTabConfigId]);

  const { configurations: crossTabConfigurations, error: crossTabError } = useAnalysis(
    profileId,
    conditions,
    status,
    rowDim && colDim ? [rowDim, colDim] : [],
  );

  const rowFacet = facets?.find((f) => f.key === rowDim);
  const colFacet = facets?.find((f) => f.key === colDim);
  const crossTabConfiguration = crossTabConfigurations?.find((c) => c.configuration_id === crossTabConfigId);

  function handleCrossTabCellClick(row: string, col: string) {
    const rowValue = resolveFacetValue(rowFacet, row);
    const colValue = resolveFacetValue(colFacet, col);
    if (!crossTabConfiguration || rowValue === undefined || colValue === undefined) return;
    const matches = matchesForConfiguration(
      crossTabConfiguration,
      requirementsById,
      groupsById,
      (r) => r.conditions[rowDim] === rowValue && r.conditions[colDim] === colValue,
    );
    setDrillDown({ label: `${crossTabConfigId} · ${rowDim}=${row} · ${colDim}=${col}`, matches });
  }

  return (
    <div className="flex flex-col gap-6">
      {facetsError && (
        <div className="rounded border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-400">{facetsError}</div>
      )}

      <div className="flex flex-wrap items-end gap-4 rounded border border-slate-800 bg-slate-900/40 p-4">
        <ConditionFacetFilters facets={facets} conditionParams={conditionParams} onConditionChange={onConditionChange} />

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

      {facets && facets.length > 0 && configurations && configurations.length > 0 && (
        <section className="flex flex-col gap-3">
          <div className="flex items-center justify-between">
            <h2 className="text-xs font-semibold uppercase tracking-wide text-slate-500">Condition breakdown</h2>
            <label className="flex items-center gap-2 text-sm text-slate-400">
              Dimension
              <select
                value={breakdownDim}
                onChange={(e) => setBreakdownDim(e.target.value)}
                className="rounded border border-slate-700 bg-slate-950 px-2 py-1.5 text-slate-100 focus:border-cyan-500/50 focus:outline-none"
              >
                {facets.map((f) => (
                  <option key={f.key} value={f.key}>
                    {f.key}
                  </option>
                ))}
              </select>
            </label>
          </div>
          <p className="text-xs text-slate-600">
            Observed coverage under each {breakdownDim || "condition"} value - not a causal claim about what caused
            it.
          </p>
          {breakdownError && (
            <div className="rounded border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-400">
              {breakdownError}
            </div>
          )}
          {breakdownFacet && breakdownConfigurations && (
            <ConditionCrossTab
              cornerLabel="Configuration"
              rowHeaderLabel="Configuration"
              columnHeaderLabel={breakdownDim}
              rowLabels={breakdownConfigurations.map((c) => c.configuration_id)}
              columnLabels={breakdownFacet.values.map((v) => String(v.value))}
              getCell={(row, col) => {
                const configuration = breakdownConfigurations.find((c) => c.configuration_id === row);
                const cell = configuration?.groups.find((g) => String(g.key[0]) === col);
                return cell?.aggregate;
              }}
              onCellClick={handleBreakdownCellClick}
            />
          )}
        </section>
      )}

      {facets && facets.length > 1 && configurations && configurations.length > 0 && (
        <section className="flex flex-col gap-3">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <h2 className="text-xs font-semibold uppercase tracking-wide text-slate-500">Condition cross-tab</h2>
            <div className="flex flex-wrap items-end gap-3">
              <label className="flex items-center gap-2 text-sm text-slate-400">
                Configuration
                <select
                  value={crossTabConfigId}
                  onChange={(e) => setCrossTabConfigId(e.target.value)}
                  className="rounded border border-slate-700 bg-slate-950 px-2 py-1.5 text-slate-100 focus:border-cyan-500/50 focus:outline-none"
                >
                  {configurations.map((c) => (
                    <option key={c.configuration_id} value={c.configuration_id}>
                      {c.configuration_id}
                    </option>
                  ))}
                </select>
              </label>
              <label className="flex items-center gap-2 text-sm text-slate-400">
                Row
                <select
                  value={rowDim}
                  onChange={(e) => setRowDim(e.target.value)}
                  className="rounded border border-slate-700 bg-slate-950 px-2 py-1.5 text-slate-100 focus:border-cyan-500/50 focus:outline-none"
                >
                  {facets.map((f) => (
                    <option key={f.key} value={f.key}>
                      {f.key}
                    </option>
                  ))}
                </select>
              </label>
              <label className="flex items-center gap-2 text-sm text-slate-400">
                Column
                <select
                  value={colDim}
                  onChange={(e) => setColDim(e.target.value)}
                  className="rounded border border-slate-700 bg-slate-950 px-2 py-1.5 text-slate-100 focus:border-cyan-500/50 focus:outline-none"
                >
                  {columnDimOptions.map((f) => (
                    <option key={f.key} value={f.key}>
                      {f.key}
                    </option>
                  ))}
                </select>
              </label>
            </div>
          </div>
          <p className="text-xs text-slate-600">
            Observed coverage for {crossTabConfigId || "the selected configuration"} under each {rowDim}/{colDim}
            {" "}combination - not a causal claim.
          </p>
          {crossTabError && (
            <div className="rounded border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-400">
              {crossTabError}
            </div>
          )}
          {rowFacet && colFacet && crossTabConfiguration && (
            <ConditionCrossTab
              cornerLabel={rowDim}
              rowHeaderLabel={rowDim}
              columnHeaderLabel={colDim}
              rowLabels={rowFacet.values.map((v) => String(v.value))}
              columnLabels={colFacet.values.map((v) => String(v.value))}
              getCell={(row, col) => {
                const cell = crossTabConfiguration.groups.find(
                  (g) => String(g.key[0]) === row && String(g.key[1]) === col,
                );
                return cell?.aggregate;
              }}
              onCellClick={handleCrossTabCellClick}
            />
          )}
        </section>
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
    </div>
  );
}
