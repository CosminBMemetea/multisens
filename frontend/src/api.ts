import type {
  AnalysisFilter,
  AnalysisResponse,
  ConfigurationCoverage,
  ConfigurationSummary,
  ConnectorDetail,
  ConnectorSummary,
  DecisionAnalysisResponse,
  DecisionPolicy,
  EvaluationProfile,
  EvaluationResult,
  EvidenceSample,
  Facet,
  GroundTruthEvent,
  PairwiseComparison,
  ParetoDirection,
  PluginDetail,
  PluginSummary,
  PredictionEvent,
  ProfileSummary,
  ProfileUsageEntry,
  ResourceCollectorSummary,
  ResourceObservation,
  Scenario,
  SensorConfig,
  Session,
  TimelineEvent,
  TradeoffResponse,
} from "./types";

// Calls happen from the browser, not from inside this container - the
// frontend container only ever serves static files, so the API base is
// wherever the browser can reach the backend container's published port,
// which is always the host regardless of how the frontend itself was
// served (dev server or the nginx-built container). No cross-container
// networking concern here at all.
export const API_BASE_URL =
  import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

export const WS_STATUS_URL = `${API_BASE_URL.replace(/^http/, "ws")}/ws/status`;

export function sensorStreamUrl(sensorId: string): string {
  return `${API_BASE_URL}/api/sensors/${sensorId}/stream.mjpeg`;
}

// Callers that need to distinguish "not found" from "backend unreachable"
// (e.g. session detail rendering a 404 state instead of a generic error)
// check `.status` rather than string-matching the message.
export class ApiError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.status = status;
  }
}

async function getJson<T>(path: string): Promise<T> {
  const res = await fetch(`${API_BASE_URL}${path}`);
  if (!res.ok) {
    throw new ApiError(`GET ${path} failed: ${res.status}`, res.status);
  }
  return res.json();
}

async function postJson<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${API_BASE_URL}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const detail = await res.json().catch(() => null);
    const suffix = detail?.detail ? ` - ${detail.detail}` : "";
    throw new ApiError(`POST ${path} failed: ${res.status}${suffix}`, res.status);
  }
  return res.json();
}

export function fetchSensors(): Promise<SensorConfig[]> {
  return getJson("/api/sensors");
}

// The backend's current SUPPORTED_RESOURCE_METRICS vocabulary, possibly
// extended by an installed ResourceCollector plugin (v0.9 bug hunt, issue
// #116) - request this instead of assuming the original six built-in
// metrics, which would silently exclude anything a plugin adds.
export function fetchResourceMetrics(): Promise<string[]> {
  return getJson("/api/resource-metrics");
}

export function fetchScenarios(): Promise<Scenario[]> {
  return getJson("/api/scenarios");
}

export function createScenario(input: { name: string }): Promise<Scenario> {
  return postJson("/api/scenarios", input);
}

export function fetchSessions(): Promise<Session[]> {
  return getJson("/api/sessions");
}

export function fetchSession(sessionId: string): Promise<Session> {
  return getJson(`/api/sessions/${sessionId}`);
}

export function createSession(input: { name: string; scenario_id: string }): Promise<Session> {
  return postJson("/api/sessions", input);
}

export function fetchSessionGroundTruth(sessionId: string): Promise<GroundTruthEvent[]> {
  return getJson(`/api/sessions/${sessionId}/ground-truth`);
}

export function fetchSessionPredictions(sessionId: string): Promise<PredictionEvent[]> {
  return getJson(`/api/sessions/${sessionId}/predictions`);
}

export function fetchSessionEvaluation(sessionId: string): Promise<EvaluationResult[]> {
  return getJson(`/api/sessions/${sessionId}/evaluation`);
}

export function runEvaluation(
  sessionId: string,
  input: { task: string; tolerance_ms?: number },
): Promise<EvaluationResult[]> {
  return postJson(`/api/sessions/${sessionId}/evaluate`, input);
}

// v0.9.1, issue #120 - Evidence Playback. positive_label is required
// (no default) - the caller must state which label is "the event of
// interest," matching the backend's own no-guessing posture.
export function fetchSessionEvidence(
  sessionId: string,
  params: { task: string; positive_label: string; tolerance_ms?: number; configuration_ids?: string[] },
): Promise<EvidenceSample[]> {
  const query = new URLSearchParams({ task: params.task, positive_label: params.positive_label });
  if (params.tolerance_ms !== undefined) {
    query.set("tolerance_ms", String(params.tolerance_ms));
  }
  for (const id of params.configuration_ids ?? []) {
    query.append("configuration_ids", id);
  }
  return getJson(`/api/sessions/${sessionId}/evidence?${query}`);
}

export function fetchSessionTimeline(
  sessionId: string,
  params: { task: string; configuration_id: string; tolerance_ms?: number },
): Promise<TimelineEvent[]> {
  const query = new URLSearchParams({
    task: params.task,
    configuration_id: params.configuration_id,
  });
  if (params.tolerance_ms !== undefined) {
    query.set("tolerance_ms", String(params.tolerance_ms));
  }
  return getJson(`/api/sessions/${sessionId}/timeline?${query}`);
}

export function fetchSessionConfigurations(sessionId: string, task: string): Promise<ConfigurationSummary[]> {
  const query = new URLSearchParams({ task });
  return getJson(`/api/sessions/${sessionId}/configurations?${query}`);
}

export function runComparison(
  sessionId: string,
  input: {
    task: string;
    baseline_configuration_id: string;
    candidate_configuration_ids?: string[];
    baseline_source_id?: string;
    candidate_source_ids?: Record<string, string>;
    tolerance_ms?: number;
    coverage_warning_threshold_pp?: number;
    min_common_sample_count?: number;
  },
): Promise<{ comparisons: PairwiseComparison[] }> {
  return postJson(`/api/sessions/${sessionId}/compare`, input);
}

export function fetchProfiles(): Promise<ProfileSummary[]> {
  return getJson("/api/profiles");
}

export function fetchProfile(profileId: string): Promise<EvaluationProfile> {
  return getJson(`/api/profiles/${profileId}`);
}

// Profile import (Profiles.tsx) deliberately does its own fetch rather
// than a postJson-based createProfile wrapper here - it needs the parsed
// `detail` array/object as-is to render one bullet per validation error,
// not postJson's pre-stringified ApiError message.

export function computeProfileCoverage(
  profileId: string,
  input: {
    configuration_ids?: string[];
    session_ids?: string[];
    requirement_bindings?: Record<string, { session_id: string; source_id?: string }>;
  } = {},
): Promise<{ configuration_coverages: ConfigurationCoverage[] }> {
  return postJson(`/api/profiles/${profileId}/coverage`, input);
}

export function fetchProfileFacets(profileId: string): Promise<Facet[]> {
  return getJson(`/api/profiles/${profileId}/facets`);
}

export function runProfileAnalysis(
  profileId: string,
  input: {
    configuration_ids?: string[];
    session_ids?: string[];
    requirement_bindings?: Record<string, { session_id: string; source_id?: string }>;
    filters?: AnalysisFilter;
    group_by?: string[];
  } = {},
): Promise<AnalysisResponse> {
  return postJson(`/api/profiles/${profileId}/analysis`, input);
}

export function fetchSessionProfileUsage(sessionId: string): Promise<ProfileUsageEntry[]> {
  return getJson(`/api/sessions/${sessionId}/profile-usage`);
}

export function runDecisionAnalysis(
  profileId: string,
  input: {
    policy: DecisionPolicy;
    configuration_ids?: string[];
    session_ids?: string[];
    requirement_bindings?: Record<string, { session_id: string; source_id?: string }>;
    filters?: AnalysisFilter;
    gap_analysis?: {
      baseline_configuration_id: string;
      candidate_configuration_id?: string;
      include_removal_sweep?: boolean;
      group_by?: string[];
    };
  },
): Promise<DecisionAnalysisResponse> {
  return postJson(`/api/profiles/${profileId}/decision-analysis`, input);
}

export function fetchSessionResourceObservations(
  sessionId: string,
  params: { configuration_id?: string; metric?: string } = {},
): Promise<ResourceObservation[]> {
  const query = new URLSearchParams(
    Object.fromEntries(Object.entries(params).filter(([, v]) => v !== undefined)) as Record<string, string>,
  );
  const suffix = query.toString() ? `?${query.toString()}` : "";
  return getJson(`/api/sessions/${sessionId}/resource-observations${suffix}`);
}

export function runTradeoffs(
  profileId: string,
  input: {
    policy: DecisionPolicy;
    session_id: string;
    configuration_ids?: string[];
    requirement_bindings?: Record<string, { session_id: string; source_id?: string }>;
    filters?: AnalysisFilter;
    resource_metrics?: string[];
    resource_constraints?: { metric: string; operator: string; value: number }[];
    pareto_dimensions?: Record<string, ParetoDirection>;
    resource_comparison?: { baseline_configuration_id: string; candidate_configuration_id: string };
  },
): Promise<TradeoffResponse> {
  return postJson(`/api/profiles/${profileId}/tradeoffs`, input);
}

// --- v0.9 Plugin SDK: read-only visibility (Phase 102, issue #103) ---------
// No corresponding POST/PUT/DELETE anywhere in this file - deliberately:
// installing/enabling/disabling a plugin and wiring a connector are both
// restart-time file changes (config/sensors.yaml, `pip install`), never
// an in-app mutation. See app/api/plugins.py's own module docstring.

export function fetchPlugins(): Promise<PluginSummary[]> {
  return getJson("/api/plugins");
}

export function fetchPlugin(pluginId: string): Promise<PluginDetail> {
  return getJson(`/api/plugins/${encodeURIComponent(pluginId)}`);
}

export function fetchConnectors(): Promise<ConnectorSummary[]> {
  return getJson("/api/connectors");
}

export function fetchConnector(sensorId: string): Promise<ConnectorDetail> {
  return getJson(`/api/connectors/${encodeURIComponent(sensorId)}`);
}

// v0.9.1, issue #111 - same read-only, no-mutation posture as the
// plugin/connector endpoints above.
export function fetchResourceCollectors(): Promise<ResourceCollectorSummary[]> {
  return getJson("/api/resource-collectors");
}
