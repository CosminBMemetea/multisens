import { type ReactNode, useMemo, useState } from "react";
import { StatusBadge } from "./StatusBadge";
import { formatFractionPercent } from "../format";
import type { GroupNode } from "../groupTree";
import type { ConfigurationCoverage, GroupCoverage, Requirement, RequirementResult } from "../types";

interface CoverageMatrixProps {
  groupTree: GroupNode[];
  configurationCoverages: ConfigurationCoverage[];
  search: string;
}

function flattenGroupCoverage(root: GroupCoverage): Map<string, GroupCoverage> {
  const flat = new Map<string, GroupCoverage>();
  function walk(node: GroupCoverage) {
    if (node.group_id !== null) flat.set(node.group_id, node);
    node.children.forEach(walk);
  }
  walk(root);
  return flat;
}

// Always both numbers together, in this exact order (raw counts first,
// then both percentages) - never requirement_coverage without
// evidence_completeness beside it. A high coverage over a near-empty
// evidence base is not the same claim as one over a complete base, and
// hiding the second number would let the first one mislead.
function GroupCoverageCell({ coverage }: { coverage: GroupCoverage | undefined }) {
  if (!coverage) return <span className="text-slate-700">—</span>;
  return (
    <div className="flex flex-col items-center gap-0.5 font-mono-data">
      <span className="text-xs text-slate-300">
        {coverage.pass_count}/{coverage.fail_count}/{coverage.na_count}
      </span>
      <span className="text-[10px] text-slate-500">
        {formatFractionPercent(coverage.requirement_coverage)} · {formatFractionPercent(coverage.evidence_completeness)}
      </span>
    </div>
  );
}

const ROW_INDENT_REM = 1.25;
const ROW_BASE_PADDING_REM = 0.75;

export function CoverageMatrix({ groupTree, configurationCoverages, search }: CoverageMatrixProps) {
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set());

  const configIds = useMemo(
    () => configurationCoverages.map((c) => c.configuration_id),
    [configurationCoverages],
  );

  const resultsByConfig = useMemo(() => {
    const byConfig = new Map<string, Map<string, RequirementResult>>();
    for (const cc of configurationCoverages) {
      byConfig.set(cc.configuration_id, new Map(cc.requirement_results.map((r) => [r.requirement_id, r])));
    }
    return byConfig;
  }, [configurationCoverages]);

  const groupCoverageByConfig = useMemo(() => {
    const byConfig = new Map<string, Map<string, GroupCoverage>>();
    for (const cc of configurationCoverages) {
      byConfig.set(cc.configuration_id, flattenGroupCoverage(cc.root));
    }
    return byConfig;
  }, [configurationCoverages]);

  function toggle(groupId: string) {
    setCollapsed((prev) => {
      const next = new Set(prev);
      if (next.has(groupId)) next.delete(groupId);
      else next.add(groupId);
      return next;
    });
  }

  const searchLower = search.trim().toLowerCase();
  function matchesSearch(requirement: Requirement): boolean {
    if (!searchLower) return true;
    return (
      requirement.name.toLowerCase().includes(searchLower) ||
      requirement.task.toLowerCase().includes(searchLower)
    );
  }
  function subtreeHasMatch(node: GroupNode): boolean {
    if (node.requirements.some(matchesSearch)) return true;
    return node.children.some(subtreeHasMatch);
  }

  function renderGroup(node: GroupNode, depth: number): ReactNode[] {
    if (searchLower && !subtreeHasMatch(node)) return [];

    const isCollapsed = collapsed.has(node.group.id);
    const requirementCount = node.requirements.length;
    const rows: ReactNode[] = [
      <tr key={`group-${node.group.id}`} className="border-b border-slate-800/60 bg-slate-900/40">
        <td
          className="px-3 py-1.5 text-left text-sm font-semibold text-slate-200"
          style={{ paddingLeft: `${ROW_BASE_PADDING_REM + depth * ROW_INDENT_REM}rem` }}
        >
          <button
            onClick={() => toggle(node.group.id)}
            className="mr-1.5 w-3 text-slate-500 hover:text-slate-300"
            aria-label={isCollapsed ? "Expand group" : "Collapse group"}
          >
            {isCollapsed ? "▶" : "▼"}
          </button>
          {node.group.name}
          {requirementCount > 0 && (
            <span className="ml-2 text-xs font-normal text-slate-500">
              {requirementCount} requirement{requirementCount === 1 ? "" : "s"}
            </span>
          )}
        </td>
        {configIds.map((cid) => (
          <td key={cid} className="px-3 py-1.5 text-center">
            <GroupCoverageCell coverage={groupCoverageByConfig.get(cid)?.get(node.group.id)} />
          </td>
        ))}
      </tr>,
    ];

    if (isCollapsed) return rows;

    for (const requirement of node.requirements.filter(matchesSearch)) {
      rows.push(
        <tr key={`req-${requirement.id}`} className="border-b border-slate-800/40 last:border-0">
          <td
            className="px-3 py-1.5 text-sm text-slate-300"
            style={{ paddingLeft: `${ROW_BASE_PADDING_REM + (depth + 1) * ROW_INDENT_REM}rem` }}
          >
            {requirement.name}
            <span className="ml-2 font-mono-data text-[10px] text-slate-600">{requirement.task}</span>
          </td>
          {configIds.map((cid) => {
            const result = resultsByConfig.get(cid)?.get(requirement.id);
            return (
              <td key={cid} className="px-3 py-1.5 text-center">
                {result ? <StatusBadge status={result.status} reasons={result.reasons} /> : "—"}
              </td>
            );
          })}
        </tr>,
      );
    }

    for (const child of node.children) {
      rows.push(...renderGroup(child, depth + 1));
    }

    return rows;
  }

  return (
    <div className="overflow-x-auto rounded border border-slate-800">
      <table className="w-full text-left text-sm">
        <thead className="border-b border-slate-800 bg-slate-900/60 text-xs uppercase tracking-wide text-slate-500">
          <tr>
            <th className="px-3 py-2 font-medium">Requirement</th>
            {configIds.map((cid) => (
              <th key={cid} className="px-3 py-2 text-center font-mono-data font-medium normal-case">
                {cid}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>{groupTree.flatMap((node) => renderGroup(node, 0))}</tbody>
      </table>
    </div>
  );
}
