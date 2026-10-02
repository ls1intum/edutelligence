import { Injectable, inject } from '@angular/core';
import { AuthService } from '../../../core/auth/services/auth.service';
import {
  StatsTab,
  TimelineRequestConfig,
  VramV2Payload,
  TimelineInitPayload,
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
export function buildStatsWsUrl(token: string): string {
  const loc = typeof window !== 'undefined' ? window.location : undefined;
  const origin = loc
    ? `${loc.protocol === 'https:' ? 'wss:' : 'ws:'}//${loc.host}`
    : '';
  return `${origin}/api/ws/stats/v2?key=${encodeURIComponent(token)}`;
}

// ─── Types ────────────────────────────────────────────────────────────────────

export interface StatsWsHandlers {
  onVramInit: (payload: VramV2Payload) => void;
  onVramDelta: (payload: VramV2Payload) => void;
  onTimelineInit: (payload: TimelineInitPayload) => void;
  /**
   * Recomputed aggregates for the same range — the same shape as
   * `timeline_init` minus its (far larger) event list. Pushed while the page is
   * open, which is what keeps the KPI counters moving.
   */
  onStats: (payload: TimelineInitPayload) => void;
  onRequestsData: (payload: { requests?: Array<any> }) => void;
}

/**
 * Who the page is looking at. Null on either side means "everyone", and the two
 * combine. Narrows everything derived from requests — aggregates, the volume
 * chart's events, the request feed — and nothing else: VRAM, lanes and GPUs
 * belong to the hardware, not to a team.
 */
export interface StatsScope {
  userId: number | null;
  teamId: number | null;
  providerId: number | null;
  errorsOnly: boolean;
}

export interface StatsWsConnectOptions {
  vramDayOffset: number;
  timeline: TimelineRequestConfig;
  scope?: StatsScope;
  /**
   * State bucket the request feed is narrowed to (queued/running/error/
   * finished), or null for all states. Feed-only: it never touches the page
   * scope, so the KPI cards and charts keep their full team/user totals.
   */
  feedStatus?: string | null;
  /**
   * Which tab is on screen. Only that tab's channel is pushed — Local
   * Providers gets VRAM, Requests gets aggregates and the feed. Stored so a
   * reconnect re-declares it instead of briefly flooding both.
   */
  interest?: StatsTab;
  handlers: StatsWsHandlers;
}

type ServerMessage =
  | { type: 'vram_init'; payload: VramV2Payload }
  | { type: 'vram_delta'; payload: VramV2Payload }
  | { type: 'timeline_init'; payload: TimelineInitPayload }
  | { type: 'stats'; payload: TimelineInitPayload }
  | { type: 'requests'; payload: { requests?: Array<any> } }
  | { type: 'pong' };

// ─── Service ─────────────────────────────────────────────────────────────────

@Injectable({ providedIn: 'root' })
export class StatsWebsocketService {
  private auth = inject(AuthService);

  private ws: WebSocket | null = null;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private pingTimer: ReturnType<typeof setInterval> | null = null;
  /** Watchdog for the wake-time liveness ping; cleared when a pong arrives. */
  private wakeProbeTimer: ReturnType<typeof setTimeout> | null = null;
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
    if (typeof window !== 'undefined') {
      window.addEventListener('online', this._handleWake);
      window.addEventListener('pageshow', this._handlePageShow);
      document.addEventListener('visibilitychange', this._handleWake);
    }
    void this._openSocket();
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

  /**
   * Narrow every request-derived push to a team and/or a requester.
   *
   * Stored on the options as well as sent, so a reconnect re-applies it — the
   * dropdowns keep showing the filter, and a socket that came back unscoped
   * would quietly refill the page with platform-wide numbers underneath them.
   * The server answers with a full re-push, since no delta turns the old scope's
   * data into the new one's.
   */
  setScope(scope: StatsScope): void {
    if (this.opts) {
      this.opts = { ...this.opts, scope };
    }
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(
        JSON.stringify({
          action: 'set_scope',
          user_id: scope.userId,
          team_id: scope.teamId,
          provider_id: scope.providerId,
          errors_only: scope.errorsOnly || null,
        })
      );
    }
  }

  /**
   * Narrow the request feed to one lifecycle bucket (queued, running, error,
   * finished); null shows all states.
   *
   * Stored on the options as well as sent, so a reconnect re-applies it — the
   * dropdown keeps showing the filter, and a socket that came back unfiltered
   * would quietly widen the list under it. The server answers with a forced
   * feed push only; the aggregates are untouched by a state filter.
   */
  setFeedStatus(status: string | null): void {
    if (this.opts) {
      this.opts = { ...this.opts, feedStatus: status };
    }
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify({ action: 'set_feed_status', status }));
    }
  }

  /**
   * Tell the server which tab is on screen so it only pushes that channel.
   *
   * Stored on the options as well as sent, so a reconnect re-declares it —
   * otherwise the first init after wake would flood both channels under a
   * page that still shows only one. The server answers with a full init for
   * the newly enabled channel.
   */
  setInterest(interest: StatsTab): void {
    if (this.opts) {
      this.opts = { ...this.opts, interest };
    }
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify({ action: 'set_interest', interest }));
    }
  }

  reconnect(): void {
    this.backoff = 2000;
    this._clearReconnectTimer();
    this._clearWakeProbeTimer();
    this._clearPingTimer();
    this._closeSocket();
    void this._openSocket();
  }

  disconnect(): void {
    this.active = false;
    if (typeof window !== 'undefined') {
      window.removeEventListener('online', this._handleWake);
      window.removeEventListener('pageshow', this._handlePageShow);
      document.removeEventListener('visibilitychange', this._handleWake);
    }
    this._clearReconnectTimer();
    this._clearWakeProbeTimer();
    this._clearPingTimer();
    this._closeSocket();
    this.opts = null;
  }

  // ── Private helpers ─────────────────────────────────────────────────────────

  /**
   * After sleep the browser often keeps readyState OPEN on a dead TCP socket.
   * A plain "already open → do nothing" check then leaves the page frozen
   * until a manual reload. Probe with a ping; if no pong arrives, force a
   * reconnect. When the socket is already gone, open immediately.
   */
  private _handleWake = (): void => {
    if (!this.active) return;
    if (typeof document !== 'undefined' && document.visibilityState === 'hidden') return;
    this.backoff = 2000;
    this._clearReconnectTimer();

    if (this.ws && this.ws.readyState === WebSocket.CONNECTING) {
      return;
    }
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this._probeSocketLiveness();
      return;
    }
    void this._openSocket();
  };

  /** bfcache restore: the socket from before freeze is never usable again. */
  private _handlePageShow = (event: PageTransitionEvent): void => {
    if (!this.active || !event.persisted) return;
    this.reconnect();
  };

  private _probeSocketLiveness(): void {
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) return;
    // One probe at a time — alt-tabbing must not stack timers that all
    // reconnect on the same dead socket.
    if (this.wakeProbeTimer !== null) return;
    try {
      this.ws.send(JSON.stringify({ action: 'ping' }));
    } catch {
      this.reconnect();
      return;
    }
    this.wakeProbeTimer = setTimeout(() => {
      this.wakeProbeTimer = null;
      // Still no pong: the OPEN socket is a zombie (typical after laptop sleep).
      this.reconnect();
    }, 3_000);
  }

  private _clearWakeProbeTimer(): void {
    if (this.wakeProbeTimer !== null) {
      clearTimeout(this.wakeProbeTimer);
      this.wakeProbeTimer = null;
    }
  }

  private _scheduleReconnect(): void {
    if (!this.active || this.reconnectTimer !== null) return;
    const delay = Math.min(this.backoff, 30_000);
    this.backoff = Math.min(this.backoff * 1.5, 30_000);
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null;
      if (this.active) void this._openSocket();
    }, delay);
  }

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

  /** Null out all handlers then close, mirroring the hook's closeSocket. */
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

  private async _openSocket(): Promise<void> {
    if (!this.active || !this.opts) return;

    // A transient token-refresh failure (network blip, wake from sleep) must
    // not end the reconnect chain — retry with backoff like a dropped socket.
    const token = await this.auth.freshToken();
    if (!token) {
      this._scheduleReconnect();
      return;
    }

    this._clearReconnectTimer();
    this._clearWakeProbeTimer();
    this._clearPingTimer();
    this._closeSocket();

    const opts = this.opts;
    const ws = new WebSocket(buildStatsWsUrl(token));
    this.ws = ws;

    ws.onopen = () => {
      if (!this.active) {
        ws.close();
        return;
      }

      this.backoff = 2000;

      // Read from this.opts, not the `opts` captured when the socket was
      // opened: a scope set while the socket was down lives on the former, and
      // the latter would re-init the session at whatever was current at connect
      // time.
      const current = this.opts ?? opts;
      ws.send(
        JSON.stringify({
          action: 'init',
          vram_day: this.currentVramDay,
          timeline: {
            start: current.timeline.start,
            end: current.timeline.end,
            target_buckets: current.timeline.targetBuckets,
          },
          user_id: current.scope?.userId ?? null,
          team_id: current.scope?.teamId ?? null,
          provider_id: current.scope?.providerId ?? null,
          errors_only: current.scope?.errorsOnly || null,
          status: current.feedStatus ?? null,
          interest: current.interest ?? null,
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
        if (msg.type === 'pong') {
          // A wake probe (or the keepalive interval) got an answer — the
          // socket is alive, so cancel any pending force-reconnect.
          this._clearWakeProbeTimer();
          return;
        }
        if (msg.type === 'vram_init') {
          opts.handlers.onVramInit(msg.payload);
        } else if (msg.type === 'vram_delta') {
          opts.handlers.onVramDelta(msg.payload);
        } else if (msg.type === 'timeline_init') {
          opts.handlers.onTimelineInit(msg.payload);
        } else if (msg.type === 'stats') {
          opts.handlers.onStats(msg.payload);
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

      this._scheduleReconnect();
    };

    ws.onerror = () => {
      // handled by onclose
    };
  }
}
