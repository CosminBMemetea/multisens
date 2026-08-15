import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  formatAgeSeconds,
  formatCoverage,
  formatDelta,
  formatDeltaPp,
  formatDuration,
  formatFractionPercent,
  formatMetric,
  formatMs,
  formatRelativeDelta,
  formatResourceValue,
} from "./format";

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

describe("formatRelativeDelta", () => {
  it("renders null as N/A", () => {
    expect(formatRelativeDelta(null)).toBe("N/A");
  });

  it("formats a positive relative change with a % sign, not pp", () => {
    // Distinct from formatDeltaPp: this is a genuine relative percentage
    // change, not percentage points of an already-percent quantity.
    expect(formatRelativeDelta(0.068)).toBe("+6.8%");
  });

  it("formats a negative relative change", () => {
    expect(formatRelativeDelta(-0.175)).toBe("-17.5%");
  });

  it("renders an exact zero without a sign", () => {
    expect(formatRelativeDelta(0)).toBe("0.0%");
  });
});

describe("formatFractionPercent", () => {
  it("renders null as N/A, not a fabricated 0%", () => {
    expect(formatFractionPercent(null)).toBe("N/A");
  });

  it("renders a real zero fraction as 0%, distinct from N/A", () => {
    expect(formatFractionPercent(0)).toBe("0%");
  });

  it("rounds to the nearest whole percent", () => {
    expect(formatFractionPercent(2 / 3)).toBe("67%");
  });

  it("renders full coverage", () => {
    expect(formatFractionPercent(1)).toBe("100%");
  });
});

describe("formatResourceValue", () => {
  it("renders null as an em dash, never a fabricated 0", () => {
    expect(formatResourceValue(null, "%")).toBe("—");
  });

  it("renders a real zero distinctly from null", () => {
    expect(formatResourceValue(0, "fps")).toBe("0 fps");
  });

  it("formats a percent with no decimals", () => {
    expect(formatResourceValue(31.2, "%")).toBe("31 %");
  });

  it("formats a megabyte value with one decimal", () => {
    expect(formatResourceValue(840.456, "MB")).toBe("840.5 MB");
  });

  it("formats a millisecond latency with no decimals", () => {
    expect(formatResourceValue(42.4, "ms")).toBe("42 ms");
  });

  it("formats a Mbps value with one decimal", () => {
    expect(formatResourceValue(9.75, "Mbps")).toBe("9.8 Mbps");
  });
});

describe("formatAgeSeconds", () => {
  it("renders null as an em dash - no sample yet, never a fabricated 0", () => {
    expect(formatAgeSeconds(null)).toBe("—");
  });

  it("renders undefined as an em dash", () => {
    expect(formatAgeSeconds(undefined)).toBe("—");
  });

  it("renders a sub-second age in milliseconds", () => {
    expect(formatAgeSeconds(0.46)).toBe("460ms");
  });

  it("renders a real zero distinctly from null/undefined", () => {
    expect(formatAgeSeconds(0)).toBe("0ms");
  });

  it("renders a one-or-more-second age in seconds with one decimal", () => {
    expect(formatAgeSeconds(4.2)).toBe("4.2s");
  });

  it("renders exactly 1 second as seconds, not milliseconds", () => {
    expect(formatAgeSeconds(1)).toBe("1.0s");
  });
});

describe("formatDuration", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-08-15T00:05:00.000Z"));
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("renders a never-started (created) session as an em dash, never a fabricated Date.now()-derived value", () => {
    // Regression test: this exact bug shipped in v0.9.0 - every demo
    // session ships in `created` status with ended_at: null, and the old
    // implementation fell back to Date.now() regardless of status,
    // rendering a fabricated multi-thousand-minute duration for every
    // one of them on the live Sessions page.
    expect(formatDuration("created", "2026-08-12T13:38:06.000Z", null)).toBe("—");
  });

  it("renders a failed session as an em dash too - not running, not completed", () => {
    expect(formatDuration("failed", "2026-08-12T13:38:06.000Z", null)).toBe("—");
  });

  it("renders a live, growing duration for a genuinely running session", () => {
    // started 90s before the faked "now" above.
    expect(formatDuration("running", "2026-08-15T00:03:30.000Z", null)).toBe("1m 30s");
  });

  it("renders the real elapsed time for a completed session, using ended_at not Date.now()", () => {
    expect(formatDuration("completed", "2026-08-15T00:00:00.000Z", "2026-08-15T00:00:45.000Z")).toBe("45s");
  });

  it("a completed session's duration is unaffected by the current time", () => {
    // Even though "now" (faked above) is much later than ended_at, the
    // duration must come from ended_at, never Date.now().
    expect(formatDuration("completed", "2026-08-14T00:00:00.000Z", "2026-08-14T00:10:00.000Z")).toBe("10m 0s");
  });

  it("formats under a minute as seconds only", () => {
    expect(formatDuration("completed", "2026-08-15T00:00:00.000Z", "2026-08-15T00:00:59.000Z")).toBe("59s");
  });
});
