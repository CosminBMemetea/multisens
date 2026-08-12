import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { TopBar } from "../components/TopBar";
import { CoverageMatrix } from "../components/CoverageMatrix";
import { ApiError, computeProfileCoverage, fetchProfile } from "../api";
import { buildGroupTree } from "../groupTree";
import type { GroupNode } from "../groupTree";
import type { ConfigurationCoverage, EvaluationProfile, Requirement } from "../types";

function ConditionChips({ conditions }: { conditions: Record<string, string | number | boolean> }) {
  const entries = Object.entries(conditions);
  if (entries.length === 0) return <span className="text-slate-600">no conditions</span>;
  return (
    <div className="flex flex-wrap gap-1">
      {entries.map(([key, value]) => (
        <span
          key={key}
          className="rounded border border-slate-700 bg-slate-950 px-1.5 py-0.5 font-mono-data text-[11px] text-slate-400"
        >
          {key}={String(value)}
        </span>
      ))}
    </div>
  );
}

function RequirementRow({ requirement }: { requirement: Requirement }) {
  return (
    <div className="flex flex-col gap-1.5 rounded border border-slate-800/60 bg-slate-950/40 p-3">
      <div className="flex items-center justify-between">
        <span className="text-sm font-medium text-slate-200">{requirement.name}</span>
        <span className="font-mono-data text-xs text-slate-500">{requirement.task}</span>
      </div>
      {requirement.description && <p className="text-xs text-slate-500">{requirement.description}</p>}
      <ConditionChips conditions={requirement.conditions} />
      <ul className="flex flex-col gap-0.5 font-mono-data text-xs text-slate-400">
        {requirement.acceptance.map((c) => (
          <li key={`${c.metric}-${c.operator}-${c.value}`}>
            {c.metric} {c.operator} {c.value}
          </li>
        ))}
      </ul>
    </div>
  );
}

function GroupNodeView({ node, depth }: { node: GroupNode; depth: number }) {
  return (
    <details open className="rounded border border-slate-800 bg-slate-900/40">
      <summary
        className="cursor-pointer select-none px-3 py-2 text-sm font-semibold text-slate-200"
        style={{ paddingLeft: `${0.75 + depth * 1.25}rem` }}
      >
        {node.group.name}
        <span className="ml-2 text-xs font-normal text-slate-500">
          {node.requirements.length > 0 && `${node.requirements.length} requirement${node.requirements.length === 1 ? "" : "s"}`}
        </span>
      </summary>
      <div className="flex flex-col gap-2 px-3 pb-3" style={{ paddingLeft: `${0.75 + depth * 1.25}rem` }}>
        {node.group.description && <p className="text-xs text-slate-500">{node.group.description}</p>}
        {node.requirements.map((r) => (
          <RequirementRow key={r.id} requirement={r} />
        ))}
        {node.children.map((child) => (
          <GroupNodeView key={child.group.id} node={child} depth={depth + 1} />
        ))}
      </div>
    </details>
  );
}

export function ProfileDetail() {
  const { profileId } = useParams<{ profileId: string }>();
  const [profile, setProfile] = useState<EvaluationProfile | null>(null);
  const [notFound, setNotFound] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [coverages, setCoverages] = useState<ConfigurationCoverage[] | null>(null);
  const [computing, setComputing] = useState(false);
  const [coverageError, setCoverageError] = useState<string | null>(null);
  const [selectedConfigIds, setSelectedConfigIds] = useState<Set<string>>(new Set());
  const [search, setSearch] = useState("");

  useEffect(() => {
    if (!profileId) return;
    let cancelled = false;

    fetchProfile(profileId)
      .then((result) => {
        if (!cancelled) setProfile(result);
      })
      .catch((err) => {
        if (cancelled) return;
        if (err instanceof ApiError && err.status === 404) {
          setNotFound(true);
        } else {
          setError(String(err));
        }
      });

    return () => {
      cancelled = true;
    };
  }, [profileId]);

  const tree = useMemo(
    () => (profile ? buildGroupTree(profile.groups, profile.requirements) : []),
    [profile],
  );

  async function handleComputeCoverage() {
    if (!profileId) return;
    setComputing(true);
    setCoverageError(null);
    try {
      const result = await computeProfileCoverage(profileId, {});
      setCoverages(result.configuration_coverages);
      // Every discovered configuration starts visible - the caller opts
      // out via the checkboxes, not in.
      setSelectedConfigIds(new Set(result.configuration_coverages.map((c) => c.configuration_id)));
    } catch (err) {
      setCoverageError(String(err));
    } finally {
      setComputing(false);
    }
  }

  function toggleConfig(configId: string) {
    setSelectedConfigIds((prev) => {
      const next = new Set(prev);
      if (next.has(configId)) next.delete(configId);
      else next.add(configId);
      return next;
    });
  }

  const visibleCoverages = useMemo(
    () => (coverages ?? []).filter((c) => selectedConfigIds.has(c.configuration_id)),
    [coverages, selectedConfigIds],
  );

  return (
    <>
      <TopBar />
      <main className="mx-auto flex max-w-6xl flex-col gap-6 p-6">
        <Link to="/profiles" className="w-fit text-sm text-cyan-400 hover:underline">
          ← Profiles
        </Link>

        {notFound && (
          <div className="rounded border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-400">
            Profile &apos;{profileId}&apos; not found.
          </div>
        )}
        {error && (
          <div className="rounded border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-400">{error}</div>
        )}

        {profile && (
          <>
            <div className="flex flex-col gap-1">
              <h1 className="text-xl font-semibold text-slate-100">
                {profile.name}{" "}
                <span className="font-mono-data text-sm font-normal text-slate-500">v{profile.version}</span>
              </h1>
              {profile.description && <p className="text-sm text-slate-400">{profile.description}</p>}
              <p className="text-xs text-slate-600">
                {profile.requirements.length} requirement{profile.requirements.length === 1 ? "" : "s"} across{" "}
                {profile.groups.length} group{profile.groups.length === 1 ? "" : "s"}
              </p>
            </div>

            {profile.metadata.synthetic === true && (
              <div className="rounded border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-sm font-medium text-amber-300">
                ⚠ SYNTHETIC DATA — generated for demonstration only. Does not
                represent real sensor performance, and is not a regulatory or
                compliance claim of any kind.
              </div>
            )}

            <div className="flex flex-col gap-2">
              {tree.map((node) => (
                <GroupNodeView key={node.group.id} node={node} depth={0} />
              ))}
            </div>

            <section className="flex flex-col gap-3">
              <div className="flex items-center justify-between">
                <h2 className="text-xs font-semibold uppercase tracking-wide text-slate-500">Coverage</h2>
                <button
                  onClick={handleComputeCoverage}
                  disabled={computing}
                  className="rounded border border-cyan-500/40 bg-cyan-500/10 px-3 py-1.5 text-sm font-medium text-cyan-400 hover:bg-cyan-500/20 disabled:opacity-50"
                >
                  {computing ? "Computing…" : coverages ? "Recompute coverage" : "Compute coverage"}
                </button>
              </div>

              {coverageError && (
                <div className="rounded border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-400">
                  {coverageError}
                </div>
              )}

              {coverages && coverages.length === 0 && (
                <p className="text-sm text-slate-500">
                  No evaluated configuration matches this profile's tasks yet - run evaluation on a session first.
                </p>
              )}

              {coverages && coverages.length > 0 && (
                <>
                  <div className="flex flex-wrap items-center gap-4">
                    <div className="flex flex-wrap gap-3">
                      {coverages.map((c) => (
                        <label key={c.configuration_id} className="flex items-center gap-1.5 text-xs text-slate-400">
                          <input
                            type="checkbox"
                            checked={selectedConfigIds.has(c.configuration_id)}
                            onChange={() => toggleConfig(c.configuration_id)}
                          />
                          <span className="font-mono-data">{c.configuration_id}</span>
                        </label>
                      ))}
                    </div>
                    <input
                      value={search}
                      onChange={(e) => setSearch(e.target.value)}
                      placeholder="Search requirements…"
                      className="ml-auto rounded border border-slate-700 bg-slate-950 px-2 py-1 text-xs text-slate-100 focus:border-cyan-500/50 focus:outline-none"
                    />
                  </div>

                  {visibleCoverages.length === 0 ? (
                    <p className="text-sm text-slate-500">No configurations selected.</p>
                  ) : (
                    <CoverageMatrix groupTree={tree} configurationCoverages={visibleCoverages} search={search} />
                  )}
                </>
              )}
            </section>
          </>
        )}
      </main>
    </>
  );
}
