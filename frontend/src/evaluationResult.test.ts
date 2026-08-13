import { describe, expect, it } from "vitest";
import { summaryColumnsFor } from "./evaluationColumns";
import { isClassificationResult, isDetectionResult, isRegressionResult, type EvaluationResult } from "./types";

// v0.8, Phase 86: the generic evaluator_type fallback path is structurally
// unreachable through the real backend - /evaluate rejects any
// evaluator_type not already in EVALUATOR_REGISTRY (Phase 79), so no
// "unknown evaluator" EvaluationResult can ever actually be persisted and
// fetched live. That's exactly why this needs a unit test using a hand-
// built object rather than live Playwright verification: it's a forward-
// compatibility guarantee (a newer backend introducing a fourth evaluator
// type before this frontend build knows about it) that has no live path
// to exercise today, but must never render a broken page.

function baseResult(overrides: Partial<EvaluationResult> & { evaluator_type: string }): EvaluationResult {
  return {
    id: "e1",
    session_id: "s1",
    configuration_id: "cfg-rgb",
    task: "t",
    format_version: "1.0",
    tolerance_ms: 100,
    sample_count: 1,
    matched_samples: 1,
    unmatched_predictions: 0,
    unmatched_ground_truth: 0,
    metrics: {},
    confusion_matrix: null,
    computed_at: "2026-01-01T00:00:00Z",
    details: null,
    ...overrides,
  } as EvaluationResult;
}

describe("evaluator_type type guards", () => {
  it("narrow correctly for each known evaluator type", () => {
    const cls = baseResult({ evaluator_type: "classification" });
    const det = baseResult({ evaluator_type: "object_detection" });
    const reg = baseResult({ evaluator_type: "regression" });

    expect(isClassificationResult(cls)).toBe(true);
    expect(isDetectionResult(cls)).toBe(false);
    expect(isRegressionResult(cls)).toBe(false);

    expect(isDetectionResult(det)).toBe(true);
    expect(isClassificationResult(det)).toBe(false);

    expect(isRegressionResult(reg)).toBe(true);
    expect(isClassificationResult(reg)).toBe(false);
  });

  it("an unrecognized evaluator_type matches none of the known guards", () => {
    const unknown = baseResult({ evaluator_type: "pose_estimation", metrics: { mpjpe: 0.05 } });
    expect(isClassificationResult(unknown)).toBe(false);
    expect(isDetectionResult(unknown)).toBe(false);
    expect(isRegressionResult(unknown)).toBe(false);
  });
});

describe("summaryColumnsFor", () => {
  it("returns the fixed classification columns", () => {
    const columns = summaryColumnsFor([baseResult({ evaluator_type: "classification" })]);
    expect(columns.map((c) => c.key)).toEqual(["accuracy", "precision_macro", "recall_macro", "f1_macro"]);
  });

  it("returns the fixed object_detection columns", () => {
    const columns = summaryColumnsFor([baseResult({ evaluator_type: "object_detection" })]);
    expect(columns.map((c) => c.key)).toEqual([
      "precision",
      "recall",
      "f1",
      "true_positives",
      "false_positives",
      "false_negatives",
      "mean_iou_matched",
    ]);
  });

  it("returns the fixed regression columns", () => {
    const columns = summaryColumnsFor([baseResult({ evaluator_type: "regression" })]);
    expect(columns.map((c) => c.key)).toEqual(["mae", "rmse", "bias", "median_absolute_error"]);
  });

  it("falls back to sorted raw metric keys for an unrecognized evaluator_type - never a broken page", () => {
    const columns = summaryColumnsFor([
      baseResult({ evaluator_type: "pose_estimation", metrics: { mpjpe: 0.05, pck: 0.9 } }),
    ]);
    expect(columns).toEqual([
      { key: "mpjpe", label: "mpjpe" },
      { key: "pck", label: "pck" },
    ]);
  });

  it("returns an empty column list for an empty result set, not a crash", () => {
    expect(summaryColumnsFor([])).toEqual([]);
  });
});
