import { Injectable, inject } from '@angular/core';
import { AuthService } from '../../../core/auth/services/auth.service';
import {
  TimelineRequestConfig,
  VramV2Payload,
  TimelineInitPayload,
  TimelineDeltaPayload,
} from '../statistics.models';

// ─── Pure helper functions (exported for unit tests) ─────────────────────────

/**
 * Returns 'all' for a negative offset, otherwise the UTC YYYY-MM-DD string
 * shifted back `offset` days from today.
 */
export function vramDayString(offset: number): string {
  if (offset < 0) return 'all';
  const d = new Date();
  d.setUTCDate(d.getUTCDate() - offset);
  return d.toISOString().slice(0, 10);
}

/**
 * Builds the WebSocket URL using window.location (web branch).
 * Path base is /api.
 */
export function buildStatsWsUrl(apiKey: string): string {
  const loc = typeof window !== 'undefined' ? window.location : undefined;
  const origin = loc
    ? `${loc.protocol === 'https:' ? 'wss:' : 'ws:'}//${loc.host}`
    : '';
  return `${origin}/api/ws/stats/v2?key=${encodeURIComponent(apiKey)}`;
}

// ─── Types ────────────────────────────────────────────────────────────────────

export interface StatsWsHandlers {
  onVramInit: (payload: VramV2Payload) => void;
  onVramDelta: (payload: VramV2Payload) => void;
  onTimelineInit: (payload: TimelineInitPayload) => void;
  onTimelineDelta: (payload: TimelineDeltaPayload) => void;
  onRequestsData: (payload: { requests?: Array<any> }) => void;
}

export interface StatsWsConnectOptions {
  vramDayOffset: number;
  timeline: TimelineRequestConfig;
  timelineDeltas: boolean;
  handlers: StatsWsHandlers;
}

type ServerMessage =
  | { type: 'vram_init'; payload: VramV2Payload }
  | { type: 'vram_delta'; payload: VramV2Payload }
  | { type: 'timeline_init'; payload: TimelineInitPayload }
  | { type: 'timeline_delta'; payload: TimelineDeltaPayload }
  | { type: 'requests'; payload: { requests?: Array<any> } }
  | { type: 'pong' };

// ─── Service ─────────────────────────────────────────────────────────────────

@Injectable({ providedIn: 'root' })
export class StatsWebsocketService {
  private auth = inject(AuthService);

  private ws: WebSocket | null = null;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private pingTimer: ReturnType<typeof setInterval> | null = null;
  private backoff = 2000;
  private active = false;

  // Stored at connect-time so reconnects use the same options
  private opts: StatsWsConnectOptions | null = null;
  private currentVramDay = '';

  // ── Public API ──────────────────────────────────────────────────────────────

  connect(opts: StatsWsConnectOptions): void {
    this.opts = opts;
    this.currentVramDay = vramDayString(opts.vramDayOffset);
    this.active = true;
    this.backoff = 2000;
    this._openSocket();
  }

  setVramDay(offset: number): void {
    const day = vramDayString(offset);
    this.currentVramDay = day;
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify({ action: 'set_vram_day', day }));
    }
  }

  setTimelineRange(t: TimelineRequestConfig): void {
    if (this.opts) {
      this.opts = { ...this.opts, timeline: t };
    }
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(
        JSON.stringify({
          action: 'set_timeline_range',
          start: t.start,
          end: t.end,
          target_buckets: t.targetBuckets,
        })
      );
    }
  }

  reconnect(): void {
    this.backoff = 2000;
    this._clearReconnectTimer();
    this._clearPingTimer();
    this._closeSocket();
    this._openSocket();
  }

  disconnect(): void {
    this.active = false;
    this._clearReconnectTimer();
    this._clearPingTimer();
    this._closeSocket();
    this.opts = null;
  }

  // ── Private helpers ─────────────────────────────────────────────────────────

  private _clearReconnectTimer(): void {
    if (this.reconnectTimer !== null) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
  }

  private _clearPingTimer(): void {
    if (this.pingTimer !== null) {
      clearInterval(this.pingTimer);
      this.pingTimer = null;
    }
  }

  /** Null out all handlers then close — mirrors the hook's closeSocket. */
  private _closeSocket(): void {
    const current = this.ws;
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
    this.ws = null;
  }

  private _openSocket(): void {
    if (!this.active || !this.opts) return;

    const apiKey = this.auth.apiKey();
    if (!apiKey) return;

    this._clearReconnectTimer();
    this._clearPingTimer();
    this._closeSocket();

    const opts = this.opts;
    const ws = new WebSocket(buildStatsWsUrl(apiKey));
    this.ws = ws;

    ws.onopen = () => {
      if (!this.active) {
        ws.close();
        return;
      }

      this.backoff = 2000;

      ws.send(
        JSON.stringify({
          action: 'init',
          vram_day: this.currentVramDay,
          timeline_deltas: opts.timelineDeltas,
          timeline: {
            start: opts.timeline.start,
            end: opts.timeline.end,
            target_buckets: opts.timeline.targetBuckets,
          },
        })
      );

      this.pingTimer = setInterval(() => {
        if (ws.readyState === WebSocket.OPEN) {
          ws.send(JSON.stringify({ action: 'ping' }));
        }
      }, 25_000);
    };

    ws.onmessage = (event: MessageEvent) => {
      try {
        const msg: ServerMessage = JSON.parse(event.data);
        if (msg.type === 'vram_init') {
          opts.handlers.onVramInit(msg.payload);
        } else if (msg.type === 'vram_delta') {
          opts.handlers.onVramDelta(msg.payload);
        } else if (msg.type === 'timeline_init') {
          opts.handlers.onTimelineInit(msg.payload);
        } else if (msg.type === 'timeline_delta') {
          opts.handlers.onTimelineDelta(msg.payload);
        } else if (msg.type === 'requests') {
          opts.handlers.onRequestsData((msg as any).payload ?? {});
        }
      } catch {
        // ignore malformed JSON
      }
    };

    ws.onclose = () => {
      // If we already replaced the socket, skip stale close events
      if (this.ws !== ws) return;
      this._clearPingTimer();
      this.ws = null;

      if (this.active) {
        const delay = Math.min(this.backoff, 30_000);
        this.backoff = Math.min(this.backoff * 1.5, 30_000);
        this.reconnectTimer = setTimeout(() => {
          if (this.active) this._openSocket();
        }, delay);
      }
    };

    ws.onerror = () => {
      // handled by onclose
    };
  }
}
