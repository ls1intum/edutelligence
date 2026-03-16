import { useCallback, useEffect, useRef, useState } from "react";
import { Platform } from "react-native";

import type { RequestEventStats } from "@/components/statistics/types";
import { API_BASE } from "@/components/statistics/constants";

export interface VramV2Payload {
  providers?: Array<{
    provider_id: number;
    name: string;
    data: Array<any>;
  }>;
  last_snapshot_id?: number;
  error?: string;
}

export interface TimelineInitPayload {
  range?: { start: string; end: string };
  bucketSeconds?: number;
  stats?: RequestEventStats;
  events?: Array<{
    request_id: string;
    enqueue_ts: string;
    timestamp_ms: number;
    is_cloud: boolean;
  }>;
  cursor?: { enqueue_ts?: string; request_id?: string };
  error?: string;
}

export interface TimelineDeltaPayload {
  events?: Array<{
    request_id: string;
    enqueue_ts: string;
    timestamp_ms: number;
    is_cloud: boolean;
  }>;
  cursor?: { enqueue_ts?: string; request_id?: string };
  bucketSeconds?: number;
  range?: { start: string; end: string };
}

export interface TimelineRequestConfig {
  start: string;
  end: string;
  targetBuckets: number;
}

type ServerMessage =
  | { type: "vram_init"; payload: VramV2Payload }
  | { type: "vram_delta"; payload: VramV2Payload }
  | { type: "timeline_init"; payload: TimelineInitPayload }
  | { type: "timeline_delta"; payload: TimelineDeltaPayload }
  | { type: "requests"; payload: { requests?: Array<any> } }
  | { type: "pong" };

export interface UseStatsWebSocketV2Options {
  enabled: boolean;
  apiKey: string | null;
  vramDayOffset: number;
  timeline: TimelineRequestConfig;
  timelineDeltas?: boolean;
  onVramInit: (payload: VramV2Payload) => void;
  onVramDelta: (payload: VramV2Payload) => void;
  onTimelineInit: (payload: TimelineInitPayload) => void;
  onTimelineDelta: (payload: TimelineDeltaPayload) => void;
  onRequestsData: (payload: { requests?: Array<any> }) => void;
}

const IS_CLIENT =
  typeof window !== "undefined" && typeof WebSocket !== "undefined";

function buildWsUrl(apiKey: string): string {
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
  return `${base}/ws/stats/v2?key=${encodeURIComponent(apiKey)}`;
}

function vramDayString(offset: number): string {
  if (offset < 0) return "all";
  const d = new Date();
  d.setUTCDate(d.getUTCDate() - offset);
  return d.toISOString().slice(0, 10);
}

export function useStatsWebSocketV2({
  enabled,
  apiKey,
  vramDayOffset,
  timeline,
  timelineDeltas = true,
  onVramInit,
  onVramDelta,
  onTimelineInit,
  onTimelineDelta,
  onRequestsData,
}: UseStatsWebSocketV2Options) {
  const [connected, setConnected] = useState(false);
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const pingTimer = useRef<ReturnType<typeof setInterval> | null>(null);
  const backoff = useRef(2000);
  const mountedRef = useRef(true);

  const onVramInitRef = useRef(onVramInit);
  onVramInitRef.current = onVramInit;
  const onVramDeltaRef = useRef(onVramDelta);
  onVramDeltaRef.current = onVramDelta;
  const onTimelineInitRef = useRef(onTimelineInit);
  onTimelineInitRef.current = onTimelineInit;
  const onTimelineDeltaRef = useRef(onTimelineDelta);
  onTimelineDeltaRef.current = onTimelineDelta;
  const onReqRef = useRef(onRequestsData);
  onReqRef.current = onRequestsData;

  const vramDayRef = useRef(vramDayString(vramDayOffset));
  const timelineRef = useRef(timeline);
  timelineRef.current = timeline;
  const timelineDeltasRef = useRef(timelineDeltas);
  timelineDeltasRef.current = timelineDeltas;

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

  const connect = useCallback(() => {
    if (!enabled || !IS_CLIENT || !apiKey) return;

    clearReconnectTimer();
    clearPingTimer();
    closeSocket();

    const ws = new WebSocket(buildWsUrl(apiKey));
    wsRef.current = ws;

    ws.onopen = () => {
      if (!mountedRef.current) {
        ws.close();
        return;
      }
      setConnected(true);
      backoff.current = 2000;

      ws.send(
        JSON.stringify({
          action: "init",
          vram_day: vramDayRef.current,
          timeline_deltas: timelineDeltasRef.current,
          timeline: {
            start: timelineRef.current.start,
            end: timelineRef.current.end,
            target_buckets: timelineRef.current.targetBuckets,
          },
        })
      );

      pingTimer.current = setInterval(() => {
        if (ws.readyState === WebSocket.OPEN) {
          ws.send(JSON.stringify({ action: "ping" }));
        }
      }, 25_000);
    };

    ws.onmessage = (event) => {
      try {
        const msg: ServerMessage = JSON.parse(event.data);
        if (msg.type === "vram_init") {
          onVramInitRef.current(msg.payload);
        } else if (msg.type === "vram_delta") {
          onVramDeltaRef.current(msg.payload);
        } else if (msg.type === "timeline_init") {
          onTimelineInitRef.current(msg.payload);
        } else if (msg.type === "timeline_delta") {
          onTimelineDeltaRef.current(msg.payload);
        } else if (msg.type === "requests") {
          onReqRef.current(msg.payload || {});
        }
      } catch {
        // ignore malformed messages
      }
    };

    ws.onclose = () => {
      if (wsRef.current !== ws) return;
      setConnected(false);
      clearPingTimer();
      wsRef.current = null;

      if (mountedRef.current && enabled) {
        const delay = Math.min(backoff.current, 30_000);
        backoff.current = Math.min(backoff.current * 1.5, 30_000);
        reconnectTimer.current = setTimeout(() => {
          if (mountedRef.current) connect();
        }, delay);
      }
    };

    ws.onerror = () => {
      // handled by onclose
    };
  }, [apiKey, clearPingTimer, clearReconnectTimer, closeSocket, enabled]);

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

  useEffect(() => {
    const nextDay = vramDayString(vramDayOffset);
    vramDayRef.current = nextDay;
    const ws = wsRef.current;
    if (enabled && ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ action: "set_vram_day", day: nextDay }));
    }
  }, [enabled, vramDayOffset]);

  useEffect(() => {
    timelineRef.current = {
      start: timeline.start,
      end: timeline.end,
      targetBuckets: timeline.targetBuckets,
    };
    const ws = wsRef.current;
    if (enabled && ws && ws.readyState === WebSocket.OPEN) {
      ws.send(
        JSON.stringify({
          action: "set_timeline_range",
          start: timeline.start,
          end: timeline.end,
          target_buckets: timeline.targetBuckets,
        })
      );
    }
  }, [enabled, timeline.start, timeline.end, timeline.targetBuckets]);

  const reconnect = useCallback(() => {
    clearReconnectTimer();
    clearPingTimer();
    closeSocket();
    backoff.current = 2000;
    connect();
  }, [clearPingTimer, clearReconnectTimer, closeSocket, connect]);

  return { connected, reconnect };
}
