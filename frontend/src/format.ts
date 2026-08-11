// "unavailable" is a real sentinel value the backend sends deliberately
// when a metric genuinely can't be measured (see rtsp_ingestion_node.py /
// sync_status_node.py docstrings) - must render as-is, never have a unit
// suffix appended to it.
export function formatMs(value: string | undefined): string {
  if (value === undefined) return "—";
  if (value === "unavailable") return value;
  return `${value}ms`;
}
