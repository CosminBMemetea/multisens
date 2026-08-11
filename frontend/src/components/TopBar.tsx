interface TopBarProps {
  wsConnected: boolean;
  connectedSensors: number;
  totalSensors: number;
}

export function TopBar({ wsConnected, connectedSensors, totalSensors }: TopBarProps) {
  return (
    <header className="flex items-center justify-between border-b border-slate-800 bg-slate-950/80 px-6 py-3">
      <div className="flex items-center gap-3">
        <span className="text-lg font-semibold tracking-tight text-slate-100">
          Multi<span className="text-cyan-400">Sens</span>
        </span>
        <span className="rounded border border-slate-700 px-2 py-0.5 text-xs text-slate-400">
          v0.1 · dev simulator session
        </span>
      </div>
      <div className="flex items-center gap-4 font-mono-data text-sm">
        <span className="text-slate-400">
          sensors <span className="text-slate-200">{connectedSensors}/{totalSensors}</span>
        </span>
        <span
          className={`flex items-center gap-1.5 rounded border px-2 py-1 text-xs font-semibold uppercase tracking-wider ${
            wsConnected
              ? "border-emerald-500/30 bg-emerald-500/15 text-emerald-400"
              : "border-red-500/30 bg-red-500/15 text-red-400"
          }`}
        >
          <span
            className={`h-2 w-2 rounded-full ${wsConnected ? "bg-emerald-400 animate-pulse" : "bg-red-400"}`}
          />
          {wsConnected ? "LIVE" : "OFFLINE"}
        </span>
      </div>
    </header>
  );
}
