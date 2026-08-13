import type { ResourceQuality } from "../types";

const QUALITY_STYLES: Record<ResourceQuality | "mixed", string> = {
  measured: "bg-emerald-500/15 text-emerald-400 border-emerald-500/30",
  declared: "bg-cyan-500/15 text-cyan-400 border-cyan-500/30",
  estimated: "bg-amber-500/15 text-amber-400 border-amber-500/30",
  unavailable: "bg-slate-800 text-slate-500 border-slate-700",
  mixed: "bg-fuchsia-500/15 text-fuchsia-400 border-fuchsia-500/30",
};

const QUALITY_LABELS: Record<ResourceQuality | "mixed", string> = {
  measured: "MEASURED",
  declared: "DECLARED",
  estimated: "ESTIMATED",
  unavailable: "UNAVAILABLE",
  mixed: "MIXED",
};

// Item-level, not a page banner - a single session can genuinely mix
// provenance across metrics (a measured fps alongside a declared
// bitrate), so every value needs its own badge, not one blanket claim
// for the whole page. Platform context (e.g. "MEASURED —
// macbook-m2-dockerdesktop") is appended whenever a real platform_id is
// known - the raw id is shown as-is, never translated into an invented
// friendly name the backend never returned.
export function ResourceQualityBadge({
  quality,
  platformId,
}: {
  quality: ResourceQuality | "mixed";
  platformId?: string;
}) {
  const showPlatform = platformId && platformId !== "unknown" && quality !== "unavailable";
  return (
    <span
      className={`inline-flex items-center gap-1 rounded border px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide ${QUALITY_STYLES[quality]}`}
      title={showPlatform ? `${QUALITY_LABELS[quality]} — ${platformId}` : QUALITY_LABELS[quality]}
    >
      {QUALITY_LABELS[quality]}
      {showPlatform && <span className="font-mono-data normal-case text-[9px] opacity-80">— {platformId}</span>}
    </span>
  );
}
