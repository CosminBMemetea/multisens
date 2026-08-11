import { useEffect, useState } from "react";
import { fetchSensors } from "./api";
import { useStatusSocket } from "./useStatusSocket";
import type { SensorConfig } from "./types";
import { TopBar } from "./components/TopBar";
import { SensorCard } from "./components/SensorCard";
import { SyncHealthPanel } from "./components/SyncHealthPanel";
import { SystemHealthPanel } from "./components/SystemHealthPanel";

function App() {
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
    <div className="min-h-screen bg-[#05070a]">
      <TopBar
        wsConnected={connected}
        connectedSensors={connectedCount}
        totalSensors={sensors.length}
      />

      <main className="mx-auto flex max-w-6xl flex-col gap-6 p-6">
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
    </div>
  );
}

export default App;
