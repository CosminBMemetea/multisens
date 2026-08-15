import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { TopBar } from "../components/TopBar";
import { SessionStatusBadge, SourceTypeBadge } from "../components/Badge";
import { EvaluationPanel } from "../components/EvaluationPanel";
import { EvidencePlayback } from "../components/EvidencePlayback";
import {
  ApiError,
  fetchProfile,
  fetchScenarios,
  fetchSensors,
  fetchSession,
  fetchSessionGroundTruth,
  fetchSessionPredictions,
  fetchSessionProfileUsage,
} from "../api";
import type {
  EvaluationProfile,
  GroundTruthEvent,
  PredictionEvent,
  ProfileUsageEntry,
  Scenario,
  SensorConfig,
  Session,
} from "../types";

interface ConfigurationSummary {
  configurationId: string;
  sensorIds: string[];
  predictionCount: number;
}

function summarizeConfigurations(predictions: PredictionEvent[]): ConfigurationSummary[] {
  const byConfig = new Map<string, ConfigurationSummary>();
  for (const p of predictions) {
    const existing = byConfig.get(p.configuration_id);
    if (existing) {
      existing.predictionCount += 1;
    } else {
      byConfig.set(p.configuration_id, {
        configurationId: p.configuration_id,
        sensorIds: p.sensor_ids,
        predictionCount: 1,
      });
    }
  }
  return [...byConfig.values()].sort((a, b) => a.configurationId.localeCompare(b.configurationId));
}

export function SessionDetail() {
  const { sessionId } = useParams<{ sessionId: string }>();
  const [session, setSession] = useState<Session | null>(null);
  const [scenario, setScenario] = useState<Scenario | null>(null);
  const [groundTruth, setGroundTruth] = useState<GroundTruthEvent[]>([]);
  const [configurations, setConfigurations] = useState<ConfigurationSummary[]>([]);
  const [sensorsById, setSensorsById] = useState<Record<string, SensorConfig>>({});
  const [profileUsage, setProfileUsage] = useState<ProfileUsageEntry[] | null>(null);
  const [profilesById, setProfilesById] = useState<Record<string, EvaluationProfile>>({});
  const [notFound, setNotFound] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Stable reference unless the actual task set changes - EvaluationPanel
  // resyncs its selected task off this array's identity.
  const tasks = useMemo(() => [...new Set(groundTruth.map((g) => g.task))].sort(), [groundTruth]);

  useEffect(() => {
    if (!sessionId) return;
    let cancelled = false;

    async function load(id: string) {
      try {
        const [sessionResult, sensors] = await Promise.all([fetchSession(id), fetchSensors()]);
        if (cancelled) return;
        setSession(sessionResult);
        setSensorsById(Object.fromEntries(sensors.map((s) => [s.id, s])));

        const [scenarios, groundTruthResult, predictions] = await Promise.all([
          fetchScenarios(),
          fetchSessionGroundTruth(id),
          fetchSessionPredictions(id),
        ]);
        if (cancelled) return;
        setScenario(scenarios.find((s) => s.id === sessionResult.scenario_id) ?? null);
        setGroundTruth(groundTruthResult);
        setConfigurations(summarizeConfigurations(predictions));
        setError(null);
      } catch (err) {
        if (cancelled) return;
        if (err instanceof ApiError && err.status === 404) {
          setNotFound(true);
        } else {
          setError(String(err));
        }
      }
    }

    load(sessionId);
    return () => {
      cancelled = true;
    };
  }, [sessionId]);

  // Independent of the load() above - a reverse-lookup failure shouldn't
  // blank out the rest of the page, and "used by zero profiles" is a
  // legitimate, common answer, not an error state.
  useEffect(() => {
    if (!sessionId) return;
    let cancelled = false;
    fetchSessionProfileUsage(sessionId)
      .then(async (usage) => {
        if (cancelled) return;
        setProfileUsage(usage);
        const profiles = await Promise.all(usage.map((u) => fetchProfile(u.profile_id)));
        if (cancelled) return;
        setProfilesById(Object.fromEntries(profiles.map((p) => [p.id, p])));
      })
      .catch(() => {
        // Requirement names fall back to raw ids below if this fails -
        // see profileUsage's own render guard.
      });
    return () => {
      cancelled = true;
    };
  }, [sessionId]);

  return (
    <>
      <TopBar />
      <main className="mx-auto flex max-w-4xl flex-col gap-6 p-6">
        <Link to="/sessions" className="w-fit text-sm text-cyan-400 hover:underline">
          ← Sessions
        </Link>

        {notFound && (
          <div className="rounded border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-400">
            Session &apos;{sessionId}&apos; not found.
          </div>
        )}
        {error && (
          <div className="rounded border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-400">
            Failed to load session: {error}
          </div>
        )}

        {session && (
          <>
            <div className="flex items-center justify-between">
              <h1 className="text-xl font-semibold text-slate-100">{session.name}</h1>
              <SessionStatusBadge status={session.status} />
            </div>

            {scenario?.tags.includes("synthetic") && (
              <div className="rounded border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-sm font-medium text-amber-300">
                ⚠ SYNTHETIC DATA — generated for demonstration only. Does not
                represent real sensor performance.
              </div>
            )}

            <section className="rounded border border-slate-800 bg-slate-900/40 p-4">
              <h2 className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">Scenario</h2>
              {scenario ? (
                <div className="flex flex-col gap-1">
                  <span className="text-slate-200">{scenario.name}</span>
                  {scenario.tags.length > 0 && (
                    <span className="text-xs text-slate-500">Tags: {scenario.tags.join(", ")}</span>
                  )}
                </div>
              ) : (
                <span className="text-slate-500">—</span>
              )}
            </section>

            <section className="rounded border border-slate-800 bg-slate-900/40 p-4">
              <h2 className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">
                Configurations
              </h2>
              {configurations.length === 0 ? (
                <span className="text-slate-500">No predictions ingested yet.</span>
              ) : (
                <div className="flex flex-col gap-2">
                  {configurations.map((c) => (
                    <div key={c.configurationId} className="flex flex-wrap items-center gap-2 font-mono-data text-sm">
                      {c.sensorIds.map((sensorId) => {
                        const sensor = sensorsById[sensorId];
                        return (
                          <span key={sensorId} className="flex items-center gap-1">
                            <span className="uppercase text-slate-300">{sensorId}</span>
                            {sensor && <SourceTypeBadge sourceType={sensor.source_type} />}
                          </span>
                        );
                      })}
                      <span className="text-slate-600">·</span>
                      <span className="text-slate-500">{c.predictionCount} predictions</span>
                    </div>
                  ))}
                </div>
              )}
            </section>

            <section className="rounded border border-slate-800 bg-slate-900/40 p-4">
              <h2 className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">
                Data coverage
              </h2>
              <dl className="grid grid-cols-2 gap-3 font-mono-data text-sm sm:grid-cols-3">
                <div>
                  <dt className="text-slate-500">Ground truth</dt>
                  <dd className="text-slate-200">{groundTruth.length}</dd>
                </div>
                {configurations.map((c) => (
                  <div key={c.configurationId}>
                    <dt className="text-slate-500">{c.configurationId}</dt>
                    <dd className="text-slate-200">{c.predictionCount}</dd>
                  </div>
                ))}
              </dl>
            </section>

            <section className="rounded border border-slate-800 bg-slate-900/40 p-4">
              <h2 className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">Used by profiles</h2>
              {profileUsage === null ? (
                <span className="text-slate-500">Loading…</span>
              ) : profileUsage.length === 0 ? (
                <span className="text-slate-500">
                  No profile's requirement conditions currently match this session's metadata.
                </span>
              ) : (
                <ul className="flex flex-col gap-2">
                  {profileUsage.map((usage) => {
                    const profile = profilesById[usage.profile_id];
                    return (
                      <li key={usage.profile_id} className="flex flex-col gap-1">
                        <Link
                          to={`/profiles/${usage.profile_id}`}
                          className="text-sm text-cyan-400 hover:underline"
                        >
                          {usage.profile_name}{" "}
                          <span className="font-mono-data text-xs text-slate-500">v{usage.profile_version}</span>
                        </Link>
                        <div className="flex flex-wrap gap-1">
                          {usage.requirement_ids.map((requirementId) => (
                            <span
                              key={requirementId}
                              className="rounded border border-slate-700 bg-slate-950 px-1.5 py-0.5 font-mono-data text-[11px] text-slate-400"
                            >
                              {profile?.requirements.find((r) => r.id === requirementId)?.name ?? requirementId}
                            </span>
                          ))}
                        </div>
                      </li>
                    );
                  })}
                </ul>
              )}
            </section>

            <EvidencePlayback sessionId={session.id} tasks={tasks} groundTruth={groundTruth} />

            <EvaluationPanel sessionId={session.id} tasks={tasks} />
          </>
        )}
      </main>
    </>
  );
}
