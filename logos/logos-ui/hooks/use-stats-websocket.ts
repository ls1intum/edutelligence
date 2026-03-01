/**
 * useStatsWebSocket – maintains a single WebSocket connection to /ws/stats
 * that replaces the three polling HTTP calls (VRAM every 5s, latest-requests
 * every 2s, and the nowMs timer).
 *
 * The hook handles:
 *  - Authentication via query-param
 *  - Automatic reconnection with exponential back-off (1s → 30s)
 *  - Sending `set_vram_day` when the day offset changes
 *  - Sending periodic pings to keep the connection alive
 *  - Clean teardown on unmount
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { Platform } from "react-native";
import { API_BASE } from "@/components/statistics/constants";

// ---------- Types ----------

export interface VramPayload {
  providers?: Array<{
    provider_id: number;
    name: string;
    data: Array<any>;
  }>;
  error?: string;
}

export interface LatestRequestsPayload {
  requests?: Array<any>;
}

type ServerMessage =
  | { type: "vram"; payload: VramPayload }
  | { type: "requests"; payload: LatestRequestsPayload }
  | { type: "pong" };

export interface UseStatsWebSocketOptions {
  enabled?: boolean;
  apiKey: string | null;
  /** 0 = today, 1 = yesterday, etc. */
  vramDayOffset: number;
  /** Called when a new VRAM snapshot arrives (only on actual changes). */
  onVramData: (payload: VramPayload) => void;
  /** Called when the latest-requests list changes. */
  onRequestsData: (payload: LatestRequestsPayload) => void;
}

// ---------- Helpers ----------

/** True when running in a browser with WebSocket support (not SSR). */
const IS_CLIENT =
  typeof window !== "undefined" && typeof WebSocket !== "undefined";

function buildWsUrl(apiKey: string): string {
  // For web: same origin, upgrade from http(s) to ws(s)
  // For native: use API_BASE and swap protocol
  let base = API_BASE;
  if (Platform.OS === "web") {
    const loc = typeof window !== "undefined" ? window.location : undefined;
    if (loc) {
      const proto = loc.protocol === "https:" ? "wss:" : "ws:";
      base = `${proto}//${loc.host}`;
    } else {
      base = API_BASE.replace(/^http/, "ws");
    }
  } else {
    base = API_BASE.replace(/^http/, "ws");
  }
  return `${base}/ws/stats?key=${encodeURIComponent(apiKey)}`;
}

function vramDayString(offset: number): string {
  const d = new Date();
  d.setUTCDate(d.getUTCDate() - offset);
  return d.toISOString().slice(0, 10);
}

// ---------- Hook ----------

export function useStatsWebSocket({
  enabled = true,
  apiKey,
  vramDayOffset,
  onVramData,
  onRequestsData,
}: UseStatsWebSocketOptions) {
  const [connected, setConnected] = useState(false);
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const pingTimer = useRef<ReturnType<typeof setInterval> | null>(null);
  const backoff = useRef(2000);
  const mountedRef = useRef(true);

  // Keep callbacks fresh without re-triggering the connection effect
  const onVramRef = useRef(onVramData);
  onVramRef.current = onVramData;
  const onReqRef = useRef(onRequestsData);
  onReqRef.current = onRequestsData;

  // Track the current vram day so the effect can send updates
  const vramDayRef = useRef(vramDayString(vramDayOffset));

  const clearReconnectTimer = useCallback(() => {
    if (reconnectTimer.current) {
      clearTimeout(reconnectTimer.current);
      reconnectTimer.current = null;
    }
  }, []);

  const clearPingTimer = useCallback(() => {
    if (pingTimer.current) {
      clearInterval(pingTimer.current);
      pingTimer.current = null;
    }
  }, []);

  const closeSocket = useCallback(() => {
    const current = wsRef.current;
    if (!current) return;
    current.onopen = null;
    current.onmessage = null;
    current.onclose = null;
    current.onerror = null;
    try {
      current.close();
    } catch {
      // ignore close failures
    }
    wsRef.current = null;
  }, []);

  // --- Core connect logic ---
  const connect = useCallback(() => {
    if (!enabled || !IS_CLIENT || !apiKey) return;

    clearReconnectTimer();
    clearPingTimer();
    closeSocket();

    const url = buildWsUrl(apiKey);
    const ws = new WebSocket(url);
    wsRef.current = ws;

    ws.onopen = () => {
      if (!mountedRef.current) {
        ws.close();
        return;
      }
      setConnected(true);
      backoff.current = 2000; // reset backoff

      // Send current vram day
      ws.send(
        JSON.stringify({ action: "set_vram_day", day: vramDayRef.current })
      );

      // Start ping every 25s to keep connection alive through proxies
      pingTimer.current = setInterval(() => {
        if (ws.readyState === WebSocket.OPEN) {
          ws.send(JSON.stringify({ action: "ping" }));
        }
      }, 25_000);
    };

    ws.onmessage = (event) => {
      try {
        const msg: ServerMessage = JSON.parse(event.data);
        if (msg.type === "vram") {
          onVramRef.current(msg.payload);
        } else if (msg.type === "requests") {
          onReqRef.current(msg.payload);
        }
        // "pong" is silently ignored
      } catch {
        // Malformed message – ignore
      }
    };

    ws.onclose = () => {
      if (wsRef.current !== ws) return;
      setConnected(false);
      clearPingTimer();
      wsRef.current = null;

      if (mountedRef.current && enabled) {
        // Reconnect with exponential backoff (cap at 30s)
        const delay = Math.min(backoff.current, 30_000);
        backoff.current = Math.min(backoff.current * 1.5, 30_000);
        reconnectTimer.current = setTimeout(() => {
          if (mountedRef.current) connect();
        }, delay);
      }
    };

    ws.onerror = () => {
      // onclose will fire after onerror
    };
  }, [apiKey, clearPingTimer, clearReconnectTimer, closeSocket, enabled]);

  // --- Manage connection lifecycle ---
  useEffect(() => {
    mountedRef.current = true;
    connect();

    return () => {
      mountedRef.current = false;
      clearReconnectTimer();
      clearPingTimer();
      closeSocket();
    };
  }, [clearPingTimer, clearReconnectTimer, closeSocket, connect]);

  // --- When vramDayOffset changes, tell the server ---
  useEffect(() => {
    const newDay = vramDayString(vramDayOffset);
    vramDayRef.current = newDay;

    const ws = wsRef.current;
    if (enabled && ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ action: "set_vram_day", day: newDay }));
    }
  }, [enabled, vramDayOffset]);

  // --- Manual reconnect (e.g. after network change) ---
  const reconnect = useCallback(() => {
    clearReconnectTimer();
    clearPingTimer();
    closeSocket();
    backoff.current = 2000;
    connect();
  }, [clearPingTimer, clearReconnectTimer, closeSocket, connect]);

  return { connected, reconnect };
}
