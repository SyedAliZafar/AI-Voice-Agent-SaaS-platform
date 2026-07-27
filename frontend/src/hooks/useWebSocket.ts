import { useEffect, useRef, useState } from "react";

interface CallEvent {
  type: string;
  payload: Record<string, unknown>;
}

export function useWebSocket(callId: string | null) {
  const [events, setEvents] = useState<CallEvent[]>([]);
  const wsRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    if (!callId) return;

    const wsUrl = (process.env.NEXT_PUBLIC_WS_URL || "ws://localhost:8000") + `/ws/calls/${callId}`;
    const ws = new WebSocket(wsUrl);
    wsRef.current = ws;

    ws.onmessage = (msg) => {
      const parsed = JSON.parse(msg.data);
      setEvents((prev) => [...prev, parsed]);
    };

    return () => ws.close();
  }, [callId]);

  return events;
}
