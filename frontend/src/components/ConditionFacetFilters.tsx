import type { Facet } from "../types";

interface ConditionFacetFiltersProps {
  facets: Facet[] | null;
  // Raw string values straight from useSearchParams, keyed by facet key.
  conditionParams: Record<string, string>;
  onConditionChange: (key: string, rawValue: string | null) => void;
}

// The condition-dimension filter bar - built dynamically from whatever
// facets a profile's requirements actually declare, no hardcoded
// condition names. Shared by every Explorer sub-tab (Explorer, Failures,
// Evidence) so "current filters" means the same thing everywhere, driven
// by the same URL state in ProfileDetail.tsx.
export function ConditionFacetFilters({ facets, conditionParams, onConditionChange }: ConditionFacetFiltersProps) {
  if (facets && facets.length === 0) {
    return <p className="text-sm text-slate-500">This profile's requirements declare no conditions to filter by.</p>;
  }
  return (
    <>
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
    </>
  );
}
