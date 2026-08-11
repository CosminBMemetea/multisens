import type { SensorConfig, SyncStatus } from "../types";
import { formatMs } from "../format";
import { LevelBadge } from "./Badge";

interface SyncHealthPanelProps {
  sync: SyncStatus | null;
  sensors: SensorConfig[];
}

export function SyncHealthPanel({ sync, sensors }: SyncHealthPanelProps) {
  return (
    <section className="rounded-lg border border-slate-800 bg-slate-950/60 p-4">
      <div className="mb-3 flex items-center justify-between">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-300">
          Sync Health
        </h2>
        {sync ? (
          <LevelBadge level={sync.level} text={sync.level} />
        ) : (
          <LevelBadge level="unknown" text="no data" />
        )}
      </div>

      <div className="grid grid-cols-2 gap-4 font-mono-data text-sm md:grid-cols-4">
        {sensors.map((s) => (
          <div key={s.id} className="flex flex-col">
            <span className="text-xs uppercase text-slate-500">{s.id} offset</span>
            <span className="text-slate-100">{formatMs(sync?.[`offset_ms_${s.id}`])}</span>
          </div>
        ))}
        <div className="flex flex-col">
          <span className="text-xs uppercase text-slate-500">max skew</span>
          <span className="text-slate-100">{formatMs(sync?.max_skew_ms)}</span>
        </div>
        <div className="flex flex-col">
          <span className="text-xs uppercase text-slate-500">tolerance</span>
          <span className="text-slate-100">{sync ? `${sync.tolerance_ms}ms` : "—"}</span>
        </div>
        <div className="flex flex-col">
          <span className="text-xs uppercase text-slate-500">sync rate</span>
          <span className="text-slate-100">
            {sync ? `${sync.synchronized_group_rate_hz}Hz` : "—"}
          </span>
        </div>
        <div className="flex flex-col">
          <span className="text-xs uppercase text-slate-500">missing</span>
          <span className="text-slate-100">{sync?.missing_sensors ?? "—"}</span>
        </div>
      </div>
    </section>
  );
}
