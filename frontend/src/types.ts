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
