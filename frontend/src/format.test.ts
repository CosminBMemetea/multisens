import { describe, expect, it } from "vitest";
import { formatMs } from "./format";

describe("formatMs", () => {
  it("renders undefined as an em dash", () => {
    expect(formatMs(undefined)).toBe("—");
  });

  it("renders the unavailable sentinel as-is, with no unit suffix", () => {
    // Regression test: this exact bug shipped once - "unavailable" is a
    // real value the backend sends deliberately, and a plain truthiness
    // check strung "ms" onto it, producing "unavailablems". See
    // docs/limitations.md / README Phase 7 history for the full story.
    expect(formatMs("unavailable")).toBe("unavailable");
  });

  it("appends ms to a real numeric string", () => {
    expect(formatMs("12.3")).toBe("12.3ms");
  });

  it("appends ms even to a zero value (a real measurement, not absence of one)", () => {
    expect(formatMs("0.0")).toBe("0.0ms");
  });

  it("appends ms to a negative offset (sensors can run ahead of the group mean)", () => {
    expect(formatMs("-4.2")).toBe("-4.2ms");
  });
});
