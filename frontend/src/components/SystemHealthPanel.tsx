import type { SystemDiagnostics } from "../types";
import { LevelBadge } from "./Badge";

function formatUptime(seconds: string | undefined): string {
  if (!seconds) return "—";
  const s = parseInt(seconds, 10);
  if (Number.isNaN(s)) return "—";
  const m = Math.floor(s / 60);
  const rem = s % 60;
  return m > 0 ? `${m}m ${rem}s` : `${rem}s`;
}

export function SystemHealthPanel({ system }: { system: SystemDiagnostics | null }) {
  return (
    <section className="rounded-lg border border-slate-800 bg-slate-950/60 p-4">
      <div className="mb-3 flex items-center justify-between">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-300">
          System Health
        </h2>
        {system ? (
          <LevelBadge level={system.level} text={system.level} />
        ) : (
          <LevelBadge level="error" text="ROS offline" />
        )}
      </div>

      <div className="grid grid-cols-2 gap-4 font-mono-data text-sm md:grid-cols-5">
        <div className="flex flex-col">
          <span className="text-xs uppercase text-slate-500">CPU</span>
          <span className="text-slate-100">{system ? `${system.cpu_percent}%` : "—"}</span>
        </div>
        <div className="flex flex-col">
          <span className="text-xs uppercase text-slate-500">RAM</span>
          <span className="text-slate-100">{system ? `${system.memory_percent}%` : "—"}</span>
        </div>
        <div className="flex flex-col">
          <span className="text-xs uppercase text-slate-500">uptime</span>
          <span className="text-slate-100">{formatUptime(system?.uptime_sec)}</span>
        </div>
        <div className="flex flex-col">
          <span className="text-xs uppercase text-slate-500">ROS status</span>
          <span className="text-slate-100">{system ? "online" : "offline"}</span>
        </div>
        <div className="flex flex-col">
          <span className="text-xs uppercase text-slate-500">connected</span>
          <span className="text-slate-100">
            {system ? `${system.connected_sensor_count}/${system.total_sensor_count}` : "—"}
          </span>
        </div>
      </div>
    </section>
  );
}
