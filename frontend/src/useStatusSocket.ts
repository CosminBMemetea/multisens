import { useEffect, useRef, useState } from "react";
import { WS_STATUS_URL } from "./api";
import type { StatusSnapshot } from "./types";

const RECONNECT_DELAY_MS = 2000;

export function useStatusSocket(): { snapshot: StatusSnapshot | null; connected: boolean } {
  const [snapshot, setSnapshot] = useState<StatusSnapshot | null>(null);
  const [connected, setConnected] = useState(false);
  const socketRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    let cancelled = false;
    let reconnectTimer: ReturnType<typeof setTimeout> | undefined;

    function connect() {
      if (cancelled) return;
      const socket = new WebSocket(WS_STATUS_URL);
      socketRef.current = socket;

      socket.onopen = () => setConnected(true);

      socket.onmessage = (event) => {
        setSnapshot(JSON.parse(event.data));
      };

      socket.onclose = () => {
        setConnected(false);
        if (!cancelled) {
          reconnectTimer = setTimeout(connect, RECONNECT_DELAY_MS);
        }
      };

      socket.onerror = () => {
        socket.close();
      };
    }

    connect();

    return () => {
      cancelled = true;
      clearTimeout(reconnectTimer);
      socketRef.current?.close();
    };
  }, []);

  return { snapshot, connected };
}
