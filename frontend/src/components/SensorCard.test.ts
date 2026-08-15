import { describe, expect, it } from "vitest";
import { inferenceStatus } from "./SensorCard";
import type { InferenceConnectorDetail } from "../types";

// v1.0-RC, issue #124 - the ACTIVE/NONE/ERROR mapping SensorCard's own
// inference status sub-block renders, kept visually and structurally
// separate from sensor connection health (a genuinely independent state
// machine - see the module's own comment).

function connector(state: InferenceConnectorDetail["state"]): InferenceConnectorDetail {
  return {
    connector_id: "vehicles-front",
    plugin_id: "acme.inference.fake",
    state,
    session_id: state === "running" ? "s1" : null,
    config: { sensor_id: "demo_rgb" },
    health: { state, last_sample_age_s: null, message: null, details: {} },
  };
}

describe("inferenceStatus", () => {
  it("is NONE when no connector targets this sensor", () => {
    expect(inferenceStatus(undefined)).toBe("NONE");
  });

  it("is ACTIVE when running", () => {
    expect(inferenceStatus(connector("running"))).toBe("ACTIVE");
  });

  it("is ACTIVE when starting (a fleeting transient state, folded into ACTIVE)", () => {
    expect(inferenceStatus(connector("starting"))).toBe("ACTIVE");
  });

  it("is ERROR when failed", () => {
    expect(inferenceStatus(connector("failed"))).toBe("ERROR");
  });

  it("is ERROR when degraded", () => {
    expect(inferenceStatus(connector("degraded"))).toBe("ERROR");
  });

  it("is NONE when stopped (configured but not currently attached)", () => {
    expect(inferenceStatus(connector("stopped"))).toBe("NONE");
  });
});
