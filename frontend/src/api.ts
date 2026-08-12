import type {
  ConfigurationSummary,
  EvaluationResult,
  GroundTruthEvent,
  PairwiseComparison,
  PredictionEvent,
  Scenario,
  SensorConfig,
  Session,
  TimelineEvent,
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
