import { isClassificationResult, isDetectionResult, isRegressionResult, type EvaluationResult } from "./types";

// Evaluator-specific summary table columns (v0.8, Phase 86).
//
// Each evaluator type has its own small, fixed metric set - shown as
// dedicated columns, same convention classification's own Accuracy/
// Precision/Recall/F1 columns already established. An evaluator_type
// this frontend build doesn't recognize falls back to whatever metric
// keys the first result actually has (sorted, generic label) - never a
// broken page (v0.8 architecture review Q29). Pulled out of
// EvaluationPanel.tsx into its own module so it's directly unit-testable
// (a plain .ts import) without pulling in React/JSX.

export interface SummaryColumn {
  key: string;
  label: string;
}

const CLASSIFICATION_COLUMNS: SummaryColumn[] = [
  { key: "accuracy", label: "Accuracy" },
  { key: "precision_macro", label: "Precision" },
  { key: "recall_macro", label: "Recall" },
  { key: "f1_macro", label: "F1" },
];

const DETECTION_COLUMNS: SummaryColumn[] = [
  { key: "precision", label: "Precision" },
  { key: "recall", label: "Recall" },
  { key: "f1", label: "F1" },
  { key: "true_positives", label: "TP" },
  { key: "false_positives", label: "FP" },
  { key: "false_negatives", label: "FN" },
  { key: "mean_iou_matched", label: "Mean IoU" },
];

const REGRESSION_COLUMNS: SummaryColumn[] = [
  { key: "mae", label: "MAE" },
  { key: "rmse", label: "RMSE" },
  { key: "bias", label: "Bias" },
  { key: "median_absolute_error", label: "Median |err|" },
];

export function summaryColumnsFor(results: EvaluationResult[]): SummaryColumn[] {
  const first = results[0];
  if (!first) return [];
  if (isClassificationResult(first)) return CLASSIFICATION_COLUMNS;
  if (isDetectionResult(first)) return DETECTION_COLUMNS;
  if (isRegressionResult(first)) return REGRESSION_COLUMNS;
  // Generic fallback: whatever metric keys this unrecognized evaluator
  // type actually produced, sorted for a stable column order.
  return Object.keys(first.metrics)
    .sort()
    .map((key) => ({ key, label: key }));
}
