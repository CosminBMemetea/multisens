import type { SensorConfig } from "./types";

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

export async function fetchSensors(): Promise<SensorConfig[]> {
  const res = await fetch(`${API_BASE_URL}/api/sensors`);
  if (!res.ok) {
    throw new Error(`GET /api/sensors failed: ${res.status}`);
  }
  return res.json();
}
