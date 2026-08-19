import type { Detection } from "./types";

// `details` is an open `Record<string, unknown>` bag (see ConnectorHealth's
// own type comment) - `detections` inside it is wire JSON from a
// third-party-extensible plugin, never trusted blindly. A malformed or
// missing entry is dropped, not thrown - one bad connector must never
// blank out every other overlay on the same card.
export function extractDetections(details: Record<string, unknown>): Detection[] {
  const raw = details["detections"];
  if (!Array.isArray(raw)) return [];
  return raw.filter(isDetection);
}

function isDetection(value: unknown): value is Detection {
  if (typeof value !== "object" || value === null) return false;
  const v = value as Record<string, unknown>;
  if (typeof v.label !== "string" || typeof v.confidence !== "number") return false;
  if (typeof v.bbox !== "object" || v.bbox === null) return false;
  const b = v.bbox as Record<string, unknown>;
  return (
    typeof b.x === "number" &&
    typeof b.y === "number" &&
    typeof b.width === "number" &&
    typeof b.height === "number"
  );
}
