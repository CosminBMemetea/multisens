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
