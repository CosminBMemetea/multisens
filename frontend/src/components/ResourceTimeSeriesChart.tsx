interface Point {
  timestamp: string;
  value: number;
}

// A plain inline SVG polyline - no charting library, matching this
// project's existing no-unnecessary-dependency posture (the Dashboard's
// own health panels are hand-built the same way). Only rendered where it
// answers a clear question ("did this metric change over the session"),
// never a decorative addition - see ResourcesPanel's own drill-down,
// which only mounts this when at least 2 points exist.
export function ResourceTimeSeriesChart({ points, unit }: { points: Point[]; unit: string }) {
  if (points.length < 2) return null;

  const width = 320;
  const height = 80;
  const padding = 4;
  const values = points.map((p) => p.value);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1; // a flat line (min === max) still renders, not a divide-by-zero

  const coords = points.map((p, i) => {
    const x = padding + (i / (points.length - 1)) * (width - 2 * padding);
    const y = height - padding - ((p.value - min) / span) * (height - 2 * padding);
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  });

  return (
    <div className="flex flex-col gap-1">
      <svg viewBox={`0 0 ${width} ${height}`} className="h-20 w-full rounded border border-slate-800 bg-slate-950">
        <polyline points={coords.join(" ")} fill="none" stroke="rgb(34 211 238)" strokeWidth={1.5} />
      </svg>
      <div className="flex justify-between font-mono-data text-[10px] text-slate-500">
        <span>
          min {min.toFixed(1)} {unit}
        </span>
        <span>{points.length} samples</span>
        <span>
          max {max.toFixed(1)} {unit}
        </span>
      </div>
    </div>
  );
}
