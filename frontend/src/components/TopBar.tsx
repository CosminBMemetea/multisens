import type { ReactNode } from "react";
import { NavLink } from "react-router-dom";

function navLinkClass({ isActive }: { isActive: boolean }): string {
  return isActive
    ? "text-cyan-400"
    : "text-slate-400 hover:text-slate-200";
}

interface TopBarProps {
  right?: ReactNode;
}

export function TopBar({ right }: TopBarProps) {
  return (
    <header className="flex items-center justify-between border-b border-slate-800 bg-slate-950/80 px-6 py-3">
      <div className="flex items-center gap-6">
        <span className="text-lg font-semibold tracking-tight text-slate-100">
          Multi<span className="text-cyan-400">Sens</span>
        </span>
        <nav className="flex items-center gap-4 text-sm font-medium">
          <NavLink to="/" end className={navLinkClass}>
            Dashboard
          </NavLink>
          <NavLink to="/sessions" className={navLinkClass}>
            Sessions
          </NavLink>
          <NavLink to="/comparison" className={navLinkClass}>
            Comparison
          </NavLink>
          <NavLink to="/profiles" className={navLinkClass}>
            Profiles
          </NavLink>
        </nav>
      </div>
      {right && <div className="flex items-center gap-4 font-mono-data text-sm">{right}</div>}
    </header>
  );
}
