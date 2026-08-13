import { useEffect, useState } from "react";
import { runProfileAnalysis } from "../api";
import type { AnalysisFilter, ConditionValue, ConfigurationAnalysis, RequirementStatus } from "../types";

// Fetches one /analysis response for a given (conditions, status, group_by)
// combination - shared by the flat summary, the per-dimension breakdown,
// the 2D cross-tab, the Failures tab, and the N/A breakdown, which differ
// only in which status they force and what they group by.
export function useAnalysis(
  profileId: string,
  conditions: Record<string, ConditionValue>,
  status: RequirementStatus | null,
  groupBy: string[] = [],
) {
  const [configurations, setConfigurations] = useState<ConfigurationAnalysis[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const key = JSON.stringify({ conditions, status, groupBy });

  useEffect(() => {
    let cancelled = false;
    setError(null);
    const filters: AnalysisFilter = { conditions, status: status ?? undefined };
    runProfileAnalysis(profileId, { filters, group_by: groupBy })
      .then((result) => {
        if (!cancelled) setConfigurations(result.configurations);
      })
      .catch((err) => {
        if (!cancelled) setError(String(err));
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [profileId, key]);

  return { configurations, error };
}
