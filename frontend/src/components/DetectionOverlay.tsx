import { extractDetections } from "../detections";
import type { InferenceConnectorDetail } from "../types";

interface DetectionOverlayProps {
  connectors: InferenceConnectorDetail[];
}

// One color per connector (by position, not identity - stable enough
// for a handful of producers on one card, no need for a hash). Distinct
// enough to tell two overlapping models' boxes apart at a glance (e.g.
// YOLO + MediaPipe both drawing on the same live RGB feed).
const OVERLAY_COLORS = ["#34d399", "#f472b6", "#60a5fa", "#fbbf24"];

// Absolutely positioned over the video `<img>` (percentage-based, so it
// tracks the rendered image size with no JS resize listener needed) -
// `pointer-events-none` throughout so it never intercepts clicks meant
// for the video itself. Detection freshness is whatever the WS push
// cadence delivers (issue #144) - deliberately decoupled from the video
// stream's own frame rate, so a slower overlay update never stalls
// playback.
export function DetectionOverlay({ connectors }: DetectionOverlayProps) {
  return (
    <div className="pointer-events-none absolute inset-0 overflow-hidden">
      {connectors.flatMap((connector, connectorIndex) => {
        const color = OVERLAY_COLORS[connectorIndex % OVERLAY_COLORS.length];
        return extractDetections(connector.health.details).map((detection, i) => (
          <div
            key={`${connector.connector_id}-${i}`}
            className="absolute border-2"
            style={{
              left: `${detection.bbox.x * 100}%`,
              top: `${detection.bbox.y * 100}%`,
              width: `${detection.bbox.width * 100}%`,
              height: `${detection.bbox.height * 100}%`,
              borderColor: color,
            }}
          >
            <span
              className="absolute -top-4 left-0 whitespace-nowrap rounded-sm px-1 text-[10px] font-semibold leading-tight text-slate-950"
              style={{ backgroundColor: color }}
            >
              {detection.label} {Math.round(detection.confidence * 100)}%
            </span>
          </div>
        ));
      })}
    </div>
  );
}
