import { type FormEvent, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { TopBar } from "../components/TopBar";
import { API_BASE_URL, fetchProfiles } from "../api";
import type { ProfileSummary } from "../types";

const EXAMPLE_PLACEHOLDER = `{
  "id": "example-profile-v1.0",
  "name": "Example Profile",
  "version": "1.0",
  "groups": [
    { "id": "group-a", "name": "Function A" }
  ],
  "requirements": [
    {
      "id": "req-001",
      "group_id": "group-a",
      "name": "Variant 1",
      "task": "presence",
      "conditions": { "illumination": "night" },
      "acceptance": [
        { "metric": "recall_macro", "operator": ">=", "value": 0.9 }
      ]
    }
  ]
}`;

// The backend's 422 `detail` takes two different shapes depending on
// which validation layer rejected the request: Phase 31's validate_profile
// returns a flat list[str] (every problem found, not just the first);
// FastAPI/Pydantic's own structural rejection (bad types, unknown
// operator) returns a list of {loc, msg, type} objects instead. Reading
// the parsed JSON directly here (rather than re-splitting an already
// array-stringified error message) is what makes both render as a clean
// one-bullet-per-problem list instead of one run-on line.
function extractErrorMessages(detail: unknown): string[] {
  if (typeof detail === "string") return [detail];
  if (Array.isArray(detail)) {
    return detail.map((item) => {
      if (typeof item === "string") return item;
      if (item && typeof item === "object" && "msg" in item) return String((item as { msg: unknown }).msg);
      return JSON.stringify(item);
    });
  }
  return [String(detail)];
}

function ImportProfileForm({ onImported }: { onImported: () => void }) {
  const [text, setText] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [errors, setErrors] = useState<string[] | null>(null);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setSubmitting(true);
    setErrors(null);
    let parsed: unknown;
    try {
      parsed = JSON.parse(text);
    } catch (err) {
      setErrors([`Invalid JSON: ${err instanceof Error ? err.message : String(err)}`]);
      setSubmitting(false);
      return;
    }
    try {
      const res = await fetch(`${API_BASE_URL}/api/profiles`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(parsed),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => null);
        setErrors(extractErrorMessages(body?.detail ?? `Request failed (${res.status})`));
        return;
      }
      setText("");
      onImported();
    } catch (err) {
      setErrors([String(err)]);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form
      onSubmit={handleSubmit}
      className="flex flex-col gap-3 rounded border border-slate-800 bg-slate-900/40 p-4"
    >
      {errors && (
        <ul className="list-inside list-disc rounded border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-400">
          {errors.map((e) => (
            <li key={e}>{e}</li>
          ))}
        </ul>
      )}

      <label className="flex flex-col gap-1 text-sm text-slate-400">
        Profile document (JSON)
        <textarea
          required
          rows={14}
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder={EXAMPLE_PLACEHOLDER}
          spellCheck={false}
          className="rounded border border-slate-700 bg-slate-950 px-2 py-1.5 font-mono-data text-xs text-slate-100 focus:border-cyan-500/50 focus:outline-none"
        />
      </label>

      <button
        type="submit"
        disabled={submitting}
        className="self-start rounded border border-cyan-500/40 bg-cyan-500/10 px-3 py-1.5 text-sm font-medium text-cyan-400 hover:bg-cyan-500/20 disabled:opacity-50"
      >
        {submitting ? "Importing…" : "Import"}
      </button>
    </form>
  );
}

export function Profiles() {
  const [profiles, setProfiles] = useState<ProfileSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [showImportForm, setShowImportForm] = useState(false);

  async function load() {
    try {
      setProfiles(await fetchProfiles());
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
          <h1 className="text-xl font-semibold text-slate-100">Profiles</h1>
          <button
            onClick={() => setShowImportForm((v) => !v)}
            className="rounded border border-cyan-500/40 bg-cyan-500/10 px-3 py-1.5 text-sm font-medium text-cyan-400 hover:bg-cyan-500/20"
          >
            {showImportForm ? "Cancel" : "+ Import Profile"}
          </button>
        </div>

        {error && (
          <div className="rounded border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-400">
            Failed to load profiles: {error}
          </div>
        )}

        {showImportForm && (
          <ImportProfileForm
            onImported={() => {
              setShowImportForm(false);
              load();
            }}
          />
        )}

        <div className="overflow-x-auto rounded border border-slate-800">
          <table className="w-full text-left text-sm">
            <thead className="border-b border-slate-800 bg-slate-900/60 text-xs uppercase tracking-wide text-slate-500">
              <tr>
                <th className="px-4 py-2 font-medium">Profile</th>
                <th className="px-4 py-2 font-medium">Version</th>
                <th className="px-4 py-2 font-medium">Description</th>
                <th className="px-4 py-2 font-medium">Requirements</th>
                <th className="px-4 py-2 font-medium">Created</th>
              </tr>
            </thead>
            <tbody>
              {profiles === null && (
                <tr>
                  <td colSpan={5} className="px-4 py-6 text-center text-slate-500">
                    Loading…
                  </td>
                </tr>
              )}
              {profiles !== null && profiles.length === 0 && (
                <tr>
                  <td colSpan={5} className="px-4 py-6 text-center text-slate-500">
                    No profiles yet.
                  </td>
                </tr>
              )}
              {profiles?.map((p) => (
                <tr key={p.id} className="border-b border-slate-800/60 last:border-0 hover:bg-slate-900/40">
                  <td className="px-4 py-2">
                    <Link to={`/profiles/${p.id}`} className="font-medium text-cyan-400 hover:underline">
                      {p.name}
                    </Link>
                    {p.metadata.synthetic === true && (
                      <span className="ml-2 rounded border border-amber-500/30 bg-amber-500/10 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-amber-400">
                        Synthetic
                      </span>
                    )}
                  </td>
                  <td className="px-4 py-2 font-mono-data text-slate-400">{p.version}</td>
                  <td className="px-4 py-2 text-slate-400">{p.description || "—"}</td>
                  <td className="px-4 py-2 font-mono-data text-slate-400">{p.requirement_count}</td>
                  <td className="px-4 py-2 font-mono-data text-slate-400">
                    {new Date(p.created_at).toLocaleString()}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </main>
    </>
  );
}
