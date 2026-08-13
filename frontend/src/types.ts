// Mirrors the plain JSON shape the backend's ros_bridge.py translates ROS
// diagnostics into (see backend/app/ros_bridge.py _status_to_dict). No ROS
// message types appear anywhere in this frontend - the backend already did
// that translation once.

export type Level = "ok" | "warn" | "error" | "stale" | "unknown";

export interface SensorDiagnostics {
  level: Level;
  message: string;
  modality: string;
  source_type: "physical" | "simulated";
  connection_state: "connected" | "disconnected";
  fps_received: string;
  fps_expected: string;
  resolution: string;
  encoding: string;
  frames_received: string;
  frames_dropped: string;
  last_frame_age_ms: string;
  reconnect_count: string;
  publish_latency_ms: string;
}

export interface SystemDiagnostics {
  level: Level;
  message: string;
  cpu_percent: string;
  memory_percent: string;
  uptime_sec: string;
  connected_sensor_count: string;
  total_sensor_count: string;
  sync_health: string;
}

export interface SyncStatus {
  level: Level;
  message: string;
  tolerance_ms: string;
  synchronized_group_rate_hz: string;
  missing_sensors: string;
  stale_sensors: string;
  max_skew_ms: string;
  // offset_ms_{modality} keys are dynamic, one per configured sensor.
  [key: `offset_ms_${string}`]: string;
}

export interface StatusSnapshot {
  sensors: Record<string, SensorDiagnostics>;
  system: SystemDiagnostics | null;
  sync: SyncStatus | null;
}

export interface SensorConfig {
  id: string;
  modality: string;
  source_type: "physical" | "simulated";
  transport: string;
  url: string;
  expected_fps?: number;
}

// Mirrors backend/app/domain/models.py (v0.2 evaluation layer). Same rule
// as above: the backend's Pydantic models are the source of truth, this
// just describes the JSON shape they serialize to over REST.

export type SessionStatus = "created" | "running" | "completed" | "failed";

export interface Scenario {
  id: string;
  name: string;
  description: string;
  tags: string[];
  metadata: Record<string, unknown>;
}

export interface Session {
  id: string;
  name: string;
  scenario_id: string;
  started_at: string;
  ended_at: string | null;
  status: SessionStatus;
  metadata: Record<string, unknown>;
}

export interface GroundTruthEvent {
  id: string;
  session_id: string;
  timestamp_ms: number;
  task: string;
  value: Record<string, unknown>;
  metadata: Record<string, unknown>;
}

export interface PredictionEvent {
  id: string;
  session_id: string;
  timestamp_ms: number;
  source_id: string;
  sensor_ids: string[];
  configuration_id: string;
  task: string;
  value: Record<string, unknown>;
  confidence: number | null;
  latency_ms: number | null;
  metadata: Record<string, unknown>;
}

// Metric values are null (not 0) when they can't be calculated - e.g. a
// class that was never predicted has undefined precision. Always render
// null as "N/A", never as "0" - see docs/evaluation.md.
export interface ConfusionMatrix {
  labels: string[];
  counts: number[][]; // counts[actual_index][predicted_index]
}

export interface EvaluationResult {
  id: string;
  session_id: string;
  configuration_id: string;
  task: string;
  format_version: string;
  tolerance_ms: number;
  sample_count: number;
  matched_samples: number;
  unmatched_predictions: number;
  unmatched_ground_truth: number;
  metrics: Record<string, number | null>;
  confusion_matrix: ConfusionMatrix | null;
  computed_at: string;
}

export type TimelineEventKind = "correct" | "incorrect" | "missing_prediction" | "unmatched_prediction";

export interface TimelineEvent {
  timestamp_ms: number;
  kind: TimelineEventKind;
  ground_truth_label: string | null;
  predicted_label: string | null;
  delta_ms: number | null;
}

// Mirrors backend/app/domain/models.py's comparison shapes (v0.3). Never a
// causal layer - see docs/comparison.md once Phase 29 writes it: this says
// two configurations measured differently, not why.

export interface ConfigurationSummary {
  configuration_id: string;
  sensor_ids: string[];
  source_ids: string[];
  prediction_count: number;
  // null (not 0) before /evaluate has run for this configuration/task.
  sample_count: number | null;
  matched_samples: number | null;
}

export interface MetricDelta {
  baseline: number | null;
  candidate: number | null;
  absolute: number | null; // candidate - baseline; null if either side is null
  relative: number | null; // absolute / abs(baseline); null if baseline is null or zero
}

export interface ComparisonMetrics {
  sample_count: number;
  matched_samples: number;
  unmatched_predictions: number;
  unmatched_ground_truth: number;
  coverage: number | null;
  metrics: Record<string, number | null>;
}

export interface ComparisonSide {
  common_sample_count: number | null; // meaningful only on the common_set side
  baseline: ComparisonMetrics;
  candidate: ComparisonMetrics;
  metric_deltas: Record<string, MetricDelta>;
  coverage_delta_pp: number | null; // percentage POINTS, never a relative percentage
  matched_sample_delta: number;
}

export type ComparisonRelationship = "direct_addition" | "direct_removal" | "general";
export type ValidityStatus = "valid" | "valid_with_warnings" | "invalid";

export interface ComparisonValidity {
  status: ValidityStatus;
  reasons: string[];
}

export interface PairwiseComparison {
  session_id: string;
  task: string;
  baseline_configuration_id: string;
  candidate_configuration_id: string;
  baseline_source_id: string;
  candidate_source_id: string;
  tolerance_ms: number;
  added_sensors: string[];
  removed_sensors: string[];
  relationship: ComparisonRelationship;
  reported: ComparisonSide;
  common_set: ComparisonSide;
  validity: ComparisonValidity;
  computed_at: string;
}

// Mirrors backend/app/domain/profiles.py and coverage.py's shapes (v0.4).
// A requirement's PASS/FAIL/N/A is a different, not-yet-built-on-top-of
// judgment than v0.3's ComparisonValidity - never a compliance/
// certification claim either, see coverage.py's module docstring.

export type AcceptanceOperator = ">=" | "<=" | ">" | "<" | "==";
export type ConditionValue = string | number | boolean;

export interface AcceptanceCriterion {
  metric: string;
  operator: AcceptanceOperator;
  value: number;
}

export interface Requirement {
  id: string;
  group_id: string;
  name: string;
  description: string;
  task: string;
  conditions: Record<string, ConditionValue>;
  acceptance: AcceptanceCriterion[];
  metadata: Record<string, unknown>;
}

export interface RequirementGroup {
  id: string;
  parent_id: string | null;
  name: string;
  description: string;
  metadata: Record<string, unknown>;
}

export interface EvaluationProfile {
  id: string;
  name: string;
  version: string;
  description: string;
  format_version: string;
  groups: RequirementGroup[];
  requirements: Requirement[];
  metadata: Record<string, unknown>;
  created_at: string;
}

export interface ProfileSummary {
  id: string;
  name: string;
  version: string;
  description: string;
  requirement_count: number;
  metadata: Record<string, unknown>;
  created_at: string;
}

export type RequirementStatus = "pass" | "fail" | "na";

export interface CriterionResult {
  metric: string;
  operator: AcceptanceOperator;
  threshold: number;
  observed: number | null;
  status: RequirementStatus;
}

export interface EvidenceReference {
  session_id: string;
  scenario_id: string;
  configuration_id: string;
  source_id: string;
  evaluation_result_id: string;
  matched_samples: number;
  sample_count: number;
  coverage: number | null;
}

export interface RequirementResult {
  profile_id: string;
  profile_version: string;
  requirement_id: string;
  configuration_id: string;
  task: string;
  status: RequirementStatus;
  reasons: string[];
  criteria: CriterionResult[];
  evidence: EvidenceReference | null;
  computed_at: string;
}

export interface GroupCoverage {
  group_id: string | null;
  name: string;
  pass_count: number;
  fail_count: number;
  na_count: number;
  requirement_coverage: number | null;
  evidence_completeness: number | null;
  children: GroupCoverage[];
}

export interface ConfigurationCoverage {
  profile_id: string;
  profile_version: string;
  configuration_id: string;
  requirement_results: RequirementResult[];
  root: GroupCoverage;
}

// Mirrors backend/app/domain/analysis.py and the /facets, /analysis API
// shapes (v0.5). A pure exploration layer over v0.4's already-computed
// RequirementResult/GroupCoverage - never re-decides pass/fail/na, only
// filters, groups, and cross-tabulates what v0.4 already decided.

export interface FacetValue {
  value: ConditionValue;
  requirement_count: number;
}

export interface Facet {
  key: string;
  values: FacetValue[];
}

export interface AnalysisFilter {
  conditions: Record<string, ConditionValue>;
  group_id?: string | null;
  task?: string | null;
  status?: RequirementStatus | null;
}

export interface AggregateCoverage {
  pass_count: number;
  fail_count: number;
  na_count: number;
  requirement_coverage: number | null;
  evidence_completeness: number | null;
}

export interface GroupCell {
  // length 1 = breakdown (single group_by dimension), length 2 = cross-tab.
  key: ConditionValue[];
  aggregate: AggregateCoverage;
}

export interface ConfigurationAnalysis {
  configuration_id: string;
  // Over the filtered population, independent of group_by.
  summary: AggregateCoverage;
  groups: GroupCell[];
  requirement_results: RequirementResult[];
}

export interface AnalysisResponse {
  configurations: ConfigurationAnalysis[];
}

export interface ProfileUsageEntry {
  profile_id: string;
  profile_name: string;
  profile_version: string;
  requirement_ids: string[];
}
