import { sensorStreamUrl } from "../api";
import { formatMs } from "../format";
import type { SensorConfig, SensorDiagnostics } from "../types";
import { LevelBadge, SourceTypeBadge } from "./Badge";

interface SensorCardProps {
  config: SensorConfig;
  diagnostics?: SensorDiagnostics;
}

export function SensorCard({ config, diagnostics }: SensorCardProps) {
  const connected = diagnostics?.connection_state === "connected";
  const level = diagnostics?.level ?? "unknown";

  return (
    <div className="flex flex-col overflow-hidden rounded-lg border border-slate-800 bg-slate-950/60">
      <div className="relative aspect-[4/3] w-full bg-black">
        {connected ? (
          // key forces a fresh <img> (and fresh MJPEG connection) if the
          // sensor drops and reconnects, rather than trying to resume a
          // dead stream.
          <img
            key={`${config.id}-${diagnostics?.reconnect_count ?? "0"}`}
            src={sensorStreamUrl(config.id)}
            alt={`${config.id} live view`}
            className="h-full w-full object-cover"
          />
        ) : (
          <div className="flex h-full w-full items-center justify-center">
            <span className="font-mono-data text-sm uppercase tracking-widest text-slate-600">
              no signal
            </span>
          </div>
        )}
        <div className="absolute left-2 top-2 flex gap-2">
          <SourceTypeBadge sourceType={config.source_type} />
        </div>
        <div className="absolute right-2 top-2">
          <LevelBadge level={level} text={diagnostics?.connection_state ?? "unknown"} />
        </div>
      </div>

      <div className="flex flex-col gap-2 p-3">
        <div className="flex items-baseline justify-between">
          <span className="text-sm font-semibold uppercase tracking-wide text-slate-200">
            {config.id}
          </span>
          <span className="text-xs text-slate-500">{config.modality}</span>
        </div>

        <dl className="grid grid-cols-2 gap-x-3 gap-y-1 font-mono-data text-xs text-slate-400">
          <div className="flex justify-between">
            <dt>fps</dt>
            <dd className="text-slate-200">{diagnostics?.fps_received ?? "—"}</dd>
          </div>
          <div className="flex justify-between">
            <dt>expected</dt>
            <dd className="text-slate-200">{diagnostics?.fps_expected ?? "—"}</dd>
          </div>
          <div className="flex justify-between">
            <dt>resolution</dt>
            <dd className="text-slate-200">{diagnostics?.resolution ?? "—"}</dd>
          </div>
          <div className="flex justify-between">
            <dt>last frame</dt>
            <dd className="text-slate-200">{formatMs(diagnostics?.last_frame_age_ms)}</dd>
          </div>
          <div className="flex justify-between">
            <dt>reconnects</dt>
            <dd className="text-slate-200">{diagnostics?.reconnect_count ?? "—"}</dd>
          </div>
          <div className="flex justify-between">
            <dt>latency</dt>
            <dd className="text-slate-200">{formatMs(diagnostics?.publish_latency_ms)}</dd>
          </div>
        </dl>
      </div>
    </div>
  );
}
