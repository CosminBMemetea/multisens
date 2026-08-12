import { describe, expect, it } from "vitest";
import { formatCoverage, formatDelta, formatDeltaPp, formatMetric, formatMs } from "./format";

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

describe("formatMetric", () => {
  it("renders null as N/A, not 0", () => {
    // Regression guard: a null metric means "not calculable" (backend
    // never coerces it to 0.0) - rendering "0" here would silently erase
    // that distinction for the user.
    expect(formatMetric(null)).toBe("N/A");
  });

  it("renders a real zero as 0.000, distinct from N/A", () => {
    expect(formatMetric(0)).toBe("0.000");
  });

  it("formats a fractional metric to 3 decimal places", () => {
    expect(formatMetric(0.6666666666666666)).toBe("0.667");
  });

  it("formats a perfect score", () => {
    expect(formatMetric(1)).toBe("1.000");
  });
});

describe("formatCoverage", () => {
  it("renders N/A when there is nothing to cover, not 0%", () => {
    expect(formatCoverage(0, 0)).toBe("N/A");
  });

  it("renders a real 0% when there is a denominator but nothing matched", () => {
    expect(formatCoverage(0, 5)).toBe("0%");
  });

  it("rounds to the nearest whole percent", () => {
    expect(formatCoverage(2, 3)).toBe("67%");
  });

  it("renders full coverage", () => {
    expect(formatCoverage(5, 5)).toBe("100%");
  });
});

describe("formatDelta", () => {
  it("renders null as N/A, not a fabricated zero", () => {
    expect(formatDelta(null)).toBe("N/A");
  });

  it("prefixes a positive delta with +", () => {
    expect(formatDelta(0.06)).toBe("+0.060");
  });

  it("leaves the sign toFixed already provides on a negative delta", () => {
    expect(formatDelta(-0.06)).toBe("-0.060");
  });

  it("renders an exact zero delta without a sign", () => {
    expect(formatDelta(0)).toBe("0.000");
  });
});

describe("formatDeltaPp", () => {
  it("renders null as N/A", () => {
    expect(formatDeltaPp(null)).toBe("N/A");
  });

  it("uses the pp suffix, never a bare percent sign", () => {
    // The one thing stopping "-4 pp" from being misread as "-4%" - a
    // different, easily-confused quantity (see docs/comparison.md).
    expect(formatDeltaPp(-4)).toBe("-4.0 pp");
    expect(formatDeltaPp(20)).toBe("+20.0 pp");
  });

  it("renders an exact zero without a sign", () => {
    expect(formatDeltaPp(0)).toBe("0.0 pp");
  });
});
