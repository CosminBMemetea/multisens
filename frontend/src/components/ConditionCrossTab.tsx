import { formatFractionPercent } from "../format";
import type { AggregateCoverage } from "../types";

interface ConditionCrossTabProps {
  cornerLabel: string;
  rowHeaderLabel: string;
  columnHeaderLabel: string;
  rowLabels: string[];
  columnLabels: string[];
  getCell: (row: string, col: string) => AggregateCoverage | undefined;
  onCellClick?: (row: string, col: string) => void;
}

// A generic row-dimension x column-dimension grid, reused verbatim for
// both the single-configuration 2D condition cross-tab and the
// configuration x condition "heatmap" - the shape (row key, column key,
// aggregate cell) is identical in both cases, only where the labels come
// from differs.
//
// Every cell shows its requirement-count denominator (n=X) directly next
// to the percentage, never percentage alone - a 100% built from n=1 and a
// 100% built from n=12 are not the same claim, and hiding the smaller one
// behind a hover-only count would let it misread as equally solid.
export function ConditionCrossTab({
  cornerLabel,
  rowHeaderLabel,
  columnHeaderLabel,
  rowLabels,
  columnLabels,
  getCell,
  onCellClick,
}: ConditionCrossTabProps) {
  return (
    <div className="overflow-x-auto rounded border border-slate-800">
      <table className="w-full text-left text-sm">
        <thead className="border-b border-slate-800 bg-slate-900/60 text-xs uppercase tracking-wide text-slate-500">
          <tr>
            <th className="px-3 py-2 font-medium" title={rowHeaderLabel} rowSpan={2}>
              {cornerLabel}
            </th>
            <th className="px-3 py-2 text-center font-medium" colSpan={columnLabels.length} title={columnHeaderLabel}>
              {columnHeaderLabel}
            </th>
          </tr>
          <tr>
            {columnLabels.map((col) => (
              <th key={col} className="px-3 py-1.5 text-center font-mono-data font-normal normal-case text-slate-400">
                {col}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rowLabels.map((row) => (
            <tr key={row} className="border-b border-slate-800/60 last:border-0">
              <td className="px-3 py-2 font-mono-data text-slate-200">{row}</td>
              {columnLabels.map((col) => (
                <CrossTabCell
                  key={col}
                  aggregate={getCell(row, col)}
                  onClick={onCellClick ? () => onCellClick(row, col) : undefined}
                />
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function CrossTabCell({ aggregate, onClick }: { aggregate: AggregateCoverage | undefined; onClick?: () => void }) {
  if (!aggregate) {
    return <td className="px-3 py-2 text-center text-slate-700">—</td>;
  }
  const total = aggregate.pass_count + aggregate.fail_count + aggregate.na_count;
  const clickable = Boolean(onClick) && total > 0;
  return (
    <td className="px-1 py-1 text-center">
      <button
        type="button"
        disabled={!clickable}
        onClick={onClick}
        title={`${aggregate.pass_count} pass / ${aggregate.fail_count} fail / ${aggregate.na_count} n/a`}
        className={`flex w-full flex-col items-center gap-0.5 rounded px-2 py-1.5 font-mono-data ${
          clickable ? "cursor-pointer hover:bg-slate-800/60" : "cursor-default"
        }`}
      >
        <span className="text-sm text-slate-200">{formatFractionPercent(aggregate.requirement_coverage)}</span>
        <span className="text-[10px] text-slate-500">n={total}</span>
      </button>
    </td>
  );
}
