import { useState } from "react";
import { RequirementDrillDown } from "./RequirementDrillDown";
import { StatusBadge } from "./StatusBadge";
import type { Requirement, RequirementResult } from "../types";

interface CellMatch {
  requirement: Requirement;
  result: RequirementResult;
  groupName: string | undefined;
}

interface CellDrillDownProps {
  profileName: string;
  profileVersion: string;
  label: string;
  matches: CellMatch[];
  onClose: () => void;
}

// A cross-tab cell can bucket more than one requirement (two requirements
// sharing the same row/column condition values) - a single match reuses
// RequirementDrillDown exactly as CoverageMatrix does; more than one gets
// a plain selectable list that opens the same RequirementDrillDown per
// pick, rather than a second bespoke detail view.
export function CellDrillDown({ profileName, profileVersion, label, matches, onClose }: CellDrillDownProps) {
  const [selected, setSelected] = useState<CellMatch | null>(matches.length === 1 ? matches[0] : null);

  if (selected) {
    return (
      <RequirementDrillDown
        profileName={profileName}
        profileVersion={profileVersion}
        groupName={selected.groupName}
        requirement={selected.requirement}
        result={selected.result}
        onClose={matches.length === 1 ? onClose : () => setSelected(null)}
      />
    );
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4"
      onClick={onClose}
      role="presentation"
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label={label}
        className="flex max-h-[85vh] w-full max-w-lg flex-col gap-3 overflow-y-auto rounded-lg border border-slate-700 bg-slate-900 p-5"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between gap-3">
          <h2 className="text-sm font-semibold text-slate-100">{label}</h2>
          <button onClick={onClose} aria-label="Close" className="text-lg leading-none text-slate-500 hover:text-slate-300">
            ×
          </button>
        </div>
        <p className="text-xs text-slate-500">{matches.length} matching requirements</p>
        <ul className="flex flex-col gap-1">
          {matches.map((m) => (
            <li key={m.requirement.id}>
              <button
                onClick={() => setSelected(m)}
                className="flex w-full items-center justify-between gap-2 rounded border border-slate-800 bg-slate-950/40 px-3 py-2 text-left text-sm text-slate-200 hover:border-cyan-500/40"
              >
                <span>
                  {m.requirement.name}{" "}
                  <span className="font-mono-data text-xs text-slate-500">{m.requirement.task}</span>
                </span>
                <StatusBadge status={m.result.status} />
              </button>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}
