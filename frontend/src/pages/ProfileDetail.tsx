import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { TopBar } from "../components/TopBar";
import { ApiError, fetchProfile } from "../api";
import type { EvaluationProfile, Requirement, RequirementGroup } from "../types";

interface GroupNode {
  group: RequirementGroup;
  children: GroupNode[];
  requirements: Requirement[];
}

// Builds the group tree from the flat parent_id adjacency list - the
// wire format is flat (same as the backend's storage), the tree is a
// pure display-time derivation, never persisted or re-sent.
function buildGroupTree(groups: RequirementGroup[], requirements: Requirement[]): GroupNode[] {
  const childrenByParent = new Map<string | null, RequirementGroup[]>();
  for (const group of groups) {
    const key = group.parent_id;
    childrenByParent.set(key, [...(childrenByParent.get(key) ?? []), group]);
  }
  const requirementsByGroup = new Map<string, Requirement[]>();
  for (const requirement of requirements) {
    const key = requirement.group_id;
    requirementsByGroup.set(key, [...(requirementsByGroup.get(key) ?? []), requirement]);
  }

  function build(group: RequirementGroup): GroupNode {
    return {
      group,
      children: (childrenByParent.get(group.id) ?? []).map(build),
      requirements: requirementsByGroup.get(group.id) ?? [],
    };
  }

  return (childrenByParent.get(null) ?? []).map(build);
}

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

  return (
    <>
      <TopBar />
      <main className="mx-auto flex max-w-4xl flex-col gap-6 p-6">
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

            <div className="flex flex-col gap-2">
              {tree.map((node) => (
                <GroupNodeView key={node.group.id} node={node} depth={0} />
              ))}
            </div>
          </>
        )}
      </main>
    </>
  );
}
