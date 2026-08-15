import { useEffect, useState } from "react";
import { TopBar } from "../components/TopBar";
import { LevelBadge } from "../components/Badge";
import { fetchConnectors, fetchPlugins, fetchResourceCollectors } from "../api";
import type {
  ConnectorState,
  ConnectorSummary,
  Level,
  PluginStatus,
  PluginSummary,
  ResourceCollectorSummary,
} from "../types";

// Read-only visibility into installed plugins and connector instances
// (v0.9, Phase 102, issue #103) - deliberately never a marketplace: no
// install/browse/download affordance anywhere on this page, no
// start/stop control, no config-editing form. A plugin's presence and a
// connector's running state are both decided entirely at container
// startup (config/sensors.yaml + `pip install`) - this page only ever
// reports what's already true, matching the read-only API it calls.

const PLUGIN_STATUS_LEVEL: Record<PluginStatus, Level> = {
  available: "ok",
  incompatible: "warn",
  load_failed: "error",
  disabled: "unknown",
};

const CONNECTOR_STATE_LEVEL: Record<ConnectorState, Level> = {
  running: "ok",
  starting: "warn",
  degraded: "warn",
  stopped: "unknown",
  failed: "error",
};

function formatDict(value: Record<string, unknown>): string {
  const entries = Object.entries(value);
  if (entries.length === 0) return "—";
  return entries.map(([k, v]) => `${k}: ${JSON.stringify(v)}`).join(", ");
}

export function Integrations() {
  const [plugins, setPlugins] = useState<PluginSummary[] | null>(null);
  const [connectors, setConnectors] = useState<ConnectorSummary[] | null>(null);
  const [resourceCollectors, setResourceCollectors] = useState<ResourceCollectorSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([fetchPlugins(), fetchConnectors(), fetchResourceCollectors()])
      .then(([p, c, rc]) => {
        setPlugins(p);
        setConnectors(c);
        setResourceCollectors(rc);
        setError(null);
      })
      .catch((err) => setError(String(err)));
  }, []);

  return (
    <>
      <TopBar />
      <main className="mx-auto flex max-w-6xl flex-col gap-6 p-6">
        <div>
          <h1 className="text-xl font-semibold text-slate-100">Integrations</h1>
          <p className="mt-1 text-sm text-slate-500">
            Installed plugins and their connector instances - read-only. Installing, enabling, or
            configuring a plugin is a deployment-time change (see docs/plugin-sdk.md), not something
            this page can do.
          </p>
        </div>

        {error && (
          <div className="rounded border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-400">
            Failed to load integrations: {error}
          </div>
        )}

        <section className="flex flex-col gap-2">
          <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-400">
            Installed Plugins
          </h2>
          <div className="overflow-x-auto rounded border border-slate-800">
            <table className="w-full text-left text-sm">
              <thead className="border-b border-slate-800 bg-slate-900/60 text-xs uppercase tracking-wide text-slate-500">
                <tr>
                  <th className="px-4 py-2 font-medium">Plugin</th>
                  <th className="px-4 py-2 font-medium">Type</th>
                  <th className="px-4 py-2 font-medium">Version</th>
                  <th className="px-4 py-2 font-medium">Distribution</th>
                  <th className="px-4 py-2 font-medium">Status</th>
                  <th className="px-4 py-2 font-medium">Detail</th>
                </tr>
              </thead>
              <tbody>
                {plugins === null && (
                  <tr>
                    <td colSpan={6} className="px-4 py-6 text-center text-slate-500">
                      Loading…
                    </td>
                  </tr>
                )}
                {plugins !== null && plugins.length === 0 && (
                  <tr>
                    <td colSpan={6} className="px-4 py-6 text-center text-slate-500">
                      No plugins discovered.
                    </td>
                  </tr>
                )}
                {plugins?.map((p) => (
                  <tr key={p.plugin_id} className="border-b border-slate-800/60 last:border-0 hover:bg-slate-900/40">
                    <td className="px-4 py-2">
                      <div className="font-medium text-slate-200">{p.name ?? p.plugin_id}</div>
                      <div className="font-mono-data text-xs text-slate-500">{p.plugin_id}</div>
                    </td>
                    <td className="px-4 py-2 text-slate-400">{p.plugin_type ?? "—"}</td>
                    <td className="px-4 py-2 font-mono-data text-slate-400">{p.version ?? "—"}</td>
                    <td className="px-4 py-2 text-slate-400">
                      {p.distribution_name ?? "—"}
                      {p.distribution_version && (
                        <span className="text-slate-600"> @{p.distribution_version}</span>
                      )}
                    </td>
                    <td className="px-4 py-2">
                      <LevelBadge level={PLUGIN_STATUS_LEVEL[p.status]} text={p.status.replace("_", " ")} />
                    </td>
                    <td className="px-4 py-2 text-xs text-slate-500">{p.error ?? "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>

        <section className="flex flex-col gap-2">
          <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-400">
            Connector Instances
          </h2>
          <p className="text-xs text-slate-500">
            One row per sensor id with a <code className="font-mono-data">connector</code> block in
            config/sensors.yaml. Video/frame health for these sensors is on the Dashboard - this table
            is the connector plugin's own lifecycle state, not a duplicate of it.
          </p>
          <div className="overflow-x-auto rounded border border-slate-800">
            <table className="w-full text-left text-sm">
              <thead className="border-b border-slate-800 bg-slate-900/60 text-xs uppercase tracking-wide text-slate-500">
                <tr>
                  <th className="px-4 py-2 font-medium">Sensor</th>
                  <th className="px-4 py-2 font-medium">Plugin</th>
                  <th className="px-4 py-2 font-medium">State</th>
                  <th className="px-4 py-2 font-medium">Config</th>
                </tr>
              </thead>
              <tbody>
                {connectors === null && (
                  <tr>
                    <td colSpan={4} className="px-4 py-6 text-center text-slate-500">
                      Loading…
                    </td>
                  </tr>
                )}
                {connectors !== null && connectors.length === 0 && (
                  <tr>
                    <td colSpan={4} className="px-4 py-6 text-center text-slate-500">
                      No connector instances configured.
                    </td>
                  </tr>
                )}
                {connectors?.map((c) => (
                  <tr key={c.sensor_id} className="border-b border-slate-800/60 last:border-0 hover:bg-slate-900/40">
                    <td className="px-4 py-2 font-medium text-slate-200">{c.sensor_id}</td>
                    <td className="px-4 py-2 font-mono-data text-xs text-slate-400">{c.plugin_id}</td>
                    <td className="px-4 py-2">
                      <LevelBadge level={CONNECTOR_STATE_LEVEL[c.state]} text={c.state} />
                    </td>
                    <td className="px-4 py-2 font-mono-data text-xs text-slate-500">
                      {formatDict(c.config)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>

        <section className="flex flex-col gap-2">
          <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-400">
            Resource Collectors
          </h2>
          <p className="text-xs text-slate-500">
            One row per <code className="font-mono-data">resource_collectors:</code> config entry.
            Session-bound: a collector only actually samples between a session's start and complete -
            "available" here just means it's configured, not that it's currently collecting. See{" "}
            <code className="font-mono-data">Session</code> column for which session (if any) it's
            attached to right now.
          </p>
          <div className="overflow-x-auto rounded border border-slate-800">
            <table className="w-full text-left text-sm">
              <thead className="border-b border-slate-800 bg-slate-900/60 text-xs uppercase tracking-wide text-slate-500">
                <tr>
                  <th className="px-4 py-2 font-medium">Collector</th>
                  <th className="px-4 py-2 font-medium">Plugin</th>
                  <th className="px-4 py-2 font-medium">State</th>
                  <th className="px-4 py-2 font-medium">Session</th>
                  <th className="px-4 py-2 font-medium">Config</th>
                </tr>
              </thead>
              <tbody>
                {resourceCollectors === null && (
                  <tr>
                    <td colSpan={5} className="px-4 py-6 text-center text-slate-500">
                      Loading…
                    </td>
                  </tr>
                )}
                {resourceCollectors !== null && resourceCollectors.length === 0 && (
                  <tr>
                    <td colSpan={5} className="px-4 py-6 text-center text-slate-500">
                      No resource collectors configured.
                    </td>
                  </tr>
                )}
                {resourceCollectors?.map((c) => (
                  <tr key={c.collector_id} className="border-b border-slate-800/60 last:border-0 hover:bg-slate-900/40">
                    <td className="px-4 py-2 font-medium text-slate-200">{c.collector_id}</td>
                    <td className="px-4 py-2 font-mono-data text-xs text-slate-400">{c.plugin_id}</td>
                    <td className="px-4 py-2">
                      <LevelBadge level={CONNECTOR_STATE_LEVEL[c.state]} text={c.state} />
                    </td>
                    <td className="px-4 py-2 font-mono-data text-xs text-slate-400">
                      {c.session_id ?? "—"}
                    </td>
                    <td className="px-4 py-2 font-mono-data text-xs text-slate-500">
                      {formatDict(c.config)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      </main>
    </>
  );
}
