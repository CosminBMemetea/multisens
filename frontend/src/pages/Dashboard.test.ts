import { describe, expect, it } from "vitest";
import { groupInferenceBySensorId } from "./Dashboard";
import type { InferenceConnectorDetail } from "../types";

// v1.x, issue #141 - multiple independent inference producers per
// sensor (e.g. YOLO + a face detector both on the same RGB feed) must
// all reach the dashboard, not just the first one discovered.

function connector(id: string, sensorId: string): InferenceConnectorDetail {
  return {
    connector_id: id,
    plugin_id: `acme.inference.${id}`,
    state: "running",
    session_id: "s1",
    config: { sensor_id: sensorId },
    health: { state: "running", last_sample_age_s: 0.5, message: null, details: {} },
  };
}

describe("groupInferenceBySensorId", () => {
  it("keeps every connector targeting the same sensor, not just the first", () => {
    const grouped = groupInferenceBySensorId([
      connector("rgb_yolo", "laptop_rgb"),
      connector("rgb_face", "laptop_rgb"),
      connector("rgb_emotion", "laptop_rgb"),
    ]);
    expect(grouped.get("laptop_rgb")?.map((c) => c.connector_id)).toEqual([
      "rgb_yolo",
      "rgb_face",
      "rgb_emotion",
    ]);
  });

  it("keeps separate sensors in separate groups", () => {
    const grouped = groupInferenceBySensorId([
      connector("rgb_yolo", "laptop_rgb"),
      connector("depth_yolo", "laptop_depth"),
    ]);
    expect(grouped.get("laptop_rgb")?.map((c) => c.connector_id)).toEqual(["rgb_yolo"]);
    expect(grouped.get("depth_yolo")).toBeUndefined();
    expect(grouped.get("laptop_depth")?.map((c) => c.connector_id)).toEqual(["depth_yolo"]);
  });

  it("skips a connector whose config has no sensor_id", () => {
    const malformed: InferenceConnectorDetail = {
      connector_id: "broken",
      plugin_id: "acme.inference.broken",
      state: "running",
      session_id: "s1",
      config: {},
      health: { state: "running", last_sample_age_s: null, message: null, details: {} },
    };
    const grouped = groupInferenceBySensorId([malformed]);
    expect(grouped.size).toBe(0);
  });

  it("returns an empty map for no connectors", () => {
    expect(groupInferenceBySensorId([]).size).toBe(0);
  });
});
