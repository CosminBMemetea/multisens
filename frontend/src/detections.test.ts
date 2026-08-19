import { describe, expect, it } from "vitest";
import { extractDetections } from "./detections";

describe("extractDetections", () => {
  it("returns detections when the shape is valid", () => {
    const details = {
      detections: [
        { label: "face", confidence: 0.91, bbox: { x: 0.1, y: 0.2, width: 0.3, height: 0.4 } },
      ],
    };
    expect(extractDetections(details)).toEqual([
      { label: "face", confidence: 0.91, bbox: { x: 0.1, y: 0.2, width: 0.3, height: 0.4 } },
    ]);
  });

  it("returns an empty array when detections is missing", () => {
    expect(extractDetections({})).toEqual([]);
  });

  it("returns an empty array when detections is not an array", () => {
    expect(extractDetections({ detections: "not-an-array" })).toEqual([]);
  });

  it("drops a malformed entry without throwing", () => {
    const details = {
      detections: [
        { label: "face", confidence: 0.9, bbox: { x: 0, y: 0, width: 0.1, height: 0.1 } },
        { label: "face" }, // missing confidence/bbox
        null,
        "garbage",
        { label: "face", confidence: 0.5, bbox: { x: 0, y: 0, width: 0.1 } }, // missing height
      ],
    };
    expect(extractDetections(details)).toEqual([
      { label: "face", confidence: 0.9, bbox: { x: 0, y: 0, width: 0.1, height: 0.1 } },
    ]);
  });

  it("keeps multiple valid detections independently", () => {
    const details = {
      detections: [
        { label: "car", confidence: 0.8, bbox: { x: 0, y: 0, width: 0.2, height: 0.2 } },
        { label: "truck", confidence: 0.6, bbox: { x: 0.5, y: 0.5, width: 0.2, height: 0.2 } },
      ],
    };
    expect(extractDetections(details)).toHaveLength(2);
  });
});
