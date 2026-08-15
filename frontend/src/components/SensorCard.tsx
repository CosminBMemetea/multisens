import { sensorStreamUrl } from "../api";
import { formatAgeSeconds, formatMs } from "../format";
import type { InferenceConnectorDetail, SensorConfig, SensorDiagnostics } from "../types";
import { InferenceStatusBadge, LevelBadge, SourceTypeBadge, type InferenceStatus } from "./Badge";

interface SensorCardProps {
  config: SensorConfig;
  diagnostics?: SensorDiagnostics;
  // v1.0-RC, issue #124 - the inference connector (if any) whose own
  // config.sensor_id matches this sensor, already matched by the caller
  // (Dashboard.tsx) from the full GET /api/inference-connectors list -
  // SensorCard itself never fetches or filters that list.
  inference?: InferenceConnectorDetail;
}

// running/starting both read as "actively attempting" - starting is a
// fleeting transient state, folding it into ACTIVE keeps exactly the
// three states the dashboard actually needs to distinguish at a glance.
// failed/degraded both read as ERROR - something is configured and was
// attempted, but broken right now.
export function inferenceStatus(inference: InferenceConnectorDetail | undefined): InferenceStatus {
  if (!inference) return "NONE";
  if (inference.state === "running" || inference.state === "starting") return "ACTIVE";
  if (inference.state === "failed" || inference.state === "degraded") return "ERROR";
  return "NONE";
}

export function SensorCard({ config, diagnostics, inference }: SensorCardProps) {
  const connected = diagnostics?.connection_state === "connected";
  const level = diagnostics?.level ?? "unknown";
  const status = inferenceStatus(inference);
  const predictionsPerSec = inference?.health.details["predictions_per_sec"];

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

        {config.derived_from_sensor_id && (
          <span className="text-xs text-slate-500">
            derived from <span className="text-slate-400">{config.derived_from_sensor_id}</span>
          </span>
        )}

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

        {/* v1.0-RC, issue #124: kept visually and structurally separate
            from sensor connection health above (a genuinely independent
            state machine, #122's own PredictionConnectorInstance) - its
            own bordered block, never merged into the diagnostics dl. */}
        <div className="flex flex-col gap-1.5 border-t border-slate-800 pt-2">
          <InferenceStatusBadge status={status} />
          {status !== "NONE" && inference && (
            <dl className="grid grid-cols-2 gap-x-3 gap-y-1 font-mono-data text-xs text-slate-400">
              <div className="col-span-2 flex justify-between">
                <dt>model</dt>
                <dd className="truncate text-slate-200" title={inference.plugin_id}>
                  {inference.plugin_id}
                </dd>
              </div>
              <div className="flex justify-between">
                <dt>fps</dt>
                <dd className="text-slate-200">
                  {typeof predictionsPerSec === "number" ? predictionsPerSec.toFixed(1) : "—"}
                </dd>
              </div>
              <div className="flex justify-between">
                <dt>last pred.</dt>
                <dd className="text-slate-200">{formatAgeSeconds(inference.health.last_sample_age_s)}</dd>
              </div>
            </dl>
          )}
        </div>
      </div>
    </div>
  );
}
