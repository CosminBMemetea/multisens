import { useEffect, useState } from "react";
import { fetchSensors } from "../api";
import { useStatusSocket } from "../useStatusSocket";
import type { SensorConfig } from "../types";
import { TopBar } from "../components/TopBar";
import { SensorCard } from "../components/SensorCard";
import { SyncHealthPanel } from "../components/SyncHealthPanel";
import { SystemHealthPanel } from "../components/SystemHealthPanel";

export function Dashboard() {
  const [sensors, setSensors] = useState<SensorConfig[]>([]);
  const [configError, setConfigError] = useState<string | null>(null);
  const { snapshot, connected } = useStatusSocket();

  useEffect(() => {
    // Refetch whenever the WebSocket (re)connects, not just once on mount:
    // if the backend wasn't ready yet at initial page load, this was the
    // only way sensors would ever appear without a manual page reload.
    // Connecting to the WS also means the backend is definitely reachable,
    // so this doubles as the retry signal for the one-shot REST call.
    if (!connected) return;
    fetchSensors()
      .then((result) => {
        setSensors(result);
        setConfigError(null);
      })
      .catch((err) => setConfigError(String(err)));
  }, [connected]);

  const connectedCount = Object.values(snapshot?.sensors ?? {}).filter(
    (s) => s.connection_state === "connected",
  ).length;

  return (
    <>
      <TopBar
        right={
          <>
            <span className="text-slate-400">
              sensors <span className="text-slate-200">{connectedCount}/{sensors.length}</span>
            </span>
            <span
              className={`flex items-center gap-1.5 rounded border px-2 py-1 text-xs font-semibold uppercase tracking-wider ${
                connected
                  ? "border-emerald-500/30 bg-emerald-500/15 text-emerald-400"
                  : "border-red-500/30 bg-red-500/15 text-red-400"
              }`}
            >
              <span
                className={`h-2 w-2 rounded-full ${connected ? "bg-emerald-400 animate-pulse" : "bg-red-400"}`}
              />
              {connected ? "LIVE" : "OFFLINE"}
            </span>
          </>
        }
      />

      <main className="mx-auto flex max-w-6xl flex-col gap-6 p-6">
        <span className="self-start rounded border border-slate-700 px-2 py-0.5 text-xs text-slate-400">
          v0.2-dev · dev simulator session
        </span>

        {configError && (
          <div className="rounded border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-400">
            Failed to load sensor config: {configError}
          </div>
        )}

        <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
          {sensors.map((s) => (
            <SensorCard key={s.id} config={s} diagnostics={snapshot?.sensors[s.id]} />
          ))}
        </div>

        <SyncHealthPanel sync={snapshot?.sync ?? null} sensors={sensors} />
        <SystemHealthPanel system={snapshot?.system ?? null} />
      </main>
    </>
  );
}
