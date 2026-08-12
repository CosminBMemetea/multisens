import { type FormEvent, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { TopBar } from "../components/TopBar";
import { SessionStatusBadge } from "../components/Badge";
import {
  createScenario,
  createSession,
  fetchScenarios,
  fetchSessionGroundTruth,
  fetchSessionPredictions,
  fetchSessions,
} from "../api";
import type { Scenario, Session } from "../types";

interface SessionRow {
  session: Session;
  scenarioName: string;
  isSynthetic: boolean;
  groundTruthCount: number;
  configurationIds: string[];
}

function formatDuration(startedAt: string, endedAt: string | null): string {
  const startMs = new Date(startedAt).getTime();
  const endMs = endedAt ? new Date(endedAt).getTime() : Date.now();
  const totalSeconds = Math.max(0, Math.round((endMs - startMs) / 1000));
  if (totalSeconds < 60) return `${totalSeconds}s`;
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return `${minutes}m ${seconds}s`;
}

const NEW_SCENARIO_OPTION = "__new_scenario__";

function CreateSessionForm({ scenarios, onCreated }: { scenarios: Scenario[]; onCreated: () => void }) {
  const [name, setName] = useState("");
  const [scenarioChoice, setScenarioChoice] = useState<string>(scenarios[0]?.id ?? NEW_SCENARIO_OPTION);
  const [newScenarioName, setNewScenarioName] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      let scenarioId = scenarioChoice;
      if (scenarioChoice === NEW_SCENARIO_OPTION) {
        if (!newScenarioName.trim()) {
          throw new Error("scenario name is required");
        }
        const scenario = await createScenario({ name: newScenarioName.trim() });
        scenarioId = scenario.id;
      }
      await createSession({ name: name.trim(), scenario_id: scenarioId });
      onCreated();
    } catch (err) {
      setError(String(err));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form
      onSubmit={handleSubmit}
      className="flex flex-col gap-3 rounded border border-slate-800 bg-slate-900/40 p-4"
    >
      {error && <div className="text-sm text-red-400">{error}</div>}

      <label className="flex flex-col gap-1 text-sm text-slate-400">
        Session name
        <input
          required
          value={name}
          onChange={(e) => setName(e.target.value)}
          className="rounded border border-slate-700 bg-slate-950 px-2 py-1.5 text-slate-100 focus:border-cyan-500/50 focus:outline-none"
        />
      </label>

      <label className="flex flex-col gap-1 text-sm text-slate-400">
        Scenario
        <select
          value={scenarioChoice}
          onChange={(e) => setScenarioChoice(e.target.value)}
          className="rounded border border-slate-700 bg-slate-950 px-2 py-1.5 text-slate-100 focus:border-cyan-500/50 focus:outline-none"
        >
          {scenarios.map((s) => (
            <option key={s.id} value={s.id}>
              {s.name}
            </option>
          ))}
          <option value={NEW_SCENARIO_OPTION}>+ New scenario…</option>
        </select>
      </label>

      {scenarioChoice === NEW_SCENARIO_OPTION && (
        <label className="flex flex-col gap-1 text-sm text-slate-400">
          New scenario name
          <input
            required
            value={newScenarioName}
            onChange={(e) => setNewScenarioName(e.target.value)}
            className="rounded border border-slate-700 bg-slate-950 px-2 py-1.5 text-slate-100 focus:border-cyan-500/50 focus:outline-none"
          />
        </label>
      )}

      <button
        type="submit"
        disabled={submitting}
        className="self-start rounded border border-cyan-500/40 bg-cyan-500/10 px-3 py-1.5 text-sm font-medium text-cyan-400 hover:bg-cyan-500/20 disabled:opacity-50"
      >
        {submitting ? "Creating…" : "Create"}
      </button>
    </form>
  );
}

export function Sessions() {
  const [rows, setRows] = useState<SessionRow[] | null>(null);
  const [scenarios, setScenarios] = useState<Scenario[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [showCreateForm, setShowCreateForm] = useState(false);

  async function load() {
    try {
      const [sessions, scenarioList] = await Promise.all([fetchSessions(), fetchScenarios()]);
      const scenarioById = new Map(scenarioList.map((s) => [s.id, s]));

      const enriched = await Promise.all(
        sessions.map(async (session): Promise<SessionRow> => {
          const [groundTruth, predictions] = await Promise.all([
            fetchSessionGroundTruth(session.id),
            fetchSessionPredictions(session.id),
          ]);
          const configurationIds = [...new Set(predictions.map((p) => p.configuration_id))].sort();
          const scenario = scenarioById.get(session.scenario_id);
          return {
            session,
            scenarioName: scenario?.name ?? session.scenario_id,
            isSynthetic: scenario?.tags.includes("synthetic") ?? false,
            groundTruthCount: groundTruth.length,
            configurationIds,
          };
        }),
      );

      setRows(enriched);
      setScenarios(scenarioList);
      setError(null);
    } catch (err) {
      setError(String(err));
    }
  }

  useEffect(() => {
    load();
  }, []);

  return (
    <>
      <TopBar />
      <main className="mx-auto flex max-w-6xl flex-col gap-6 p-6">
        <div className="flex items-center justify-between">
          <h1 className="text-xl font-semibold text-slate-100">Sessions</h1>
          <button
            onClick={() => setShowCreateForm((v) => !v)}
            className="rounded border border-cyan-500/40 bg-cyan-500/10 px-3 py-1.5 text-sm font-medium text-cyan-400 hover:bg-cyan-500/20"
          >
            {showCreateForm ? "Cancel" : "+ Create Session"}
          </button>
        </div>

        {error && (
          <div className="rounded border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-400">
            Failed to load sessions: {error}
          </div>
        )}

        {showCreateForm && (
          <CreateSessionForm
            scenarios={scenarios}
            onCreated={() => {
              setShowCreateForm(false);
              load();
            }}
          />
        )}

        <div className="overflow-x-auto rounded border border-slate-800">
          <table className="w-full text-left text-sm">
            <thead className="border-b border-slate-800 bg-slate-900/60 text-xs uppercase tracking-wide text-slate-500">
              <tr>
                <th className="px-4 py-2 font-medium">Session</th>
                <th className="px-4 py-2 font-medium">Scenario</th>
                <th className="px-4 py-2 font-medium">Status</th>
                <th className="px-4 py-2 font-medium">Started</th>
                <th className="px-4 py-2 font-medium">Duration</th>
                <th className="px-4 py-2 font-medium">Configurations</th>
                <th className="px-4 py-2 font-medium">Ground truth</th>
              </tr>
            </thead>
            <tbody>
              {rows === null && (
                <tr>
                  <td colSpan={7} className="px-4 py-6 text-center text-slate-500">
                    Loading…
                  </td>
                </tr>
              )}
              {rows !== null && rows.length === 0 && (
                <tr>
                  <td colSpan={7} className="px-4 py-6 text-center text-slate-500">
                    No sessions yet.
                  </td>
                </tr>
              )}
              {rows?.map(({ session, scenarioName, isSynthetic, groundTruthCount, configurationIds }) => (
                <tr key={session.id} className="border-b border-slate-800/60 last:border-0 hover:bg-slate-900/40">
                  <td className="px-4 py-2">
                    <Link to={`/sessions/${session.id}`} className="font-medium text-cyan-400 hover:underline">
                      {session.name}
                    </Link>
                  </td>
                  <td className="px-4 py-2 text-slate-300">
                    {scenarioName}
                    {isSynthetic && (
                      <span className="ml-2 rounded border border-amber-500/30 bg-amber-500/10 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-amber-400">
                        Synthetic
                      </span>
                    )}
                  </td>
                  <td className="px-4 py-2">
                    <SessionStatusBadge status={session.status} />
                  </td>
                  <td className="px-4 py-2 font-mono-data text-slate-400">
                    {new Date(session.started_at).toLocaleString()}
                  </td>
                  <td className="px-4 py-2 font-mono-data text-slate-400">
                    {formatDuration(session.started_at, session.ended_at)}
                  </td>
                  <td className="px-4 py-2 text-slate-400">
                    {configurationIds.length > 0 ? configurationIds.join(", ") : "—"}
                  </td>
                  <td className="px-4 py-2 font-mono-data text-slate-400">{groundTruthCount}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </main>
    </>
  );
}
