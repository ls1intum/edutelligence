import { Injectable, inject, signal } from '@angular/core';
import { HttpClient, HttpParams } from '@angular/common/http';
import { firstValueFrom } from 'rxjs';
import { AuthService } from '../auth/services/auth.service';

/** The event vocabulary the application server accepts (`NotificationType`). */
export type NotificationType =
  | 'deployment'
  | 'model_request_succeeded'
  | 'batch_job_finished'
  | 'budget_hit'
  | 'new_models_available'
  | 'model_access_requested'
  | 'benchmark_result_ready'
  | 'calibration_failed';

/** One inbox item, as `GET /me/notifications` and the socket push render it. */
export interface AppNotification {
  id: number;
  type: NotificationType | string;
  title: string;
  body: string | null;
  payload: unknown;
  source: string;
  actor_user_id: number | null;
  created_at: string;
  read: boolean;
}

/** The slice of Spring's page envelope the inbox reads. */
export interface NotificationPage {
  content: AppNotification[];
  total_elements: number;
  total_pages: number;
  number: number;
  last: boolean;
}

/** Accent of a type's icon: neutral news, good news, needs attention, went wrong. */
export type NotificationTone = 'primary' | 'success' | 'warning' | 'error';

export interface NotificationTypeMeta {
  label: string;
  icon: string;
  tone: NotificationTone;
}

/** How each event type is labelled and drawn. Unknown types fall back to a bell. */
export const NOTIFICATION_TYPE_META: Record<string, NotificationTypeMeta> = {
  deployment: { label: 'Deployment', icon: 'pi-server', tone: 'success' },
  model_request_succeeded: { label: 'Model available', icon: 'pi-check-circle', tone: 'success' },
  batch_job_finished: { label: 'Batch finished', icon: 'pi-list-check', tone: 'success' },
  budget_hit: { label: 'Budget reached', icon: 'pi-wallet', tone: 'warning' },
  new_models_available: { label: 'New models', icon: 'pi-sparkles', tone: 'primary' },
  model_access_requested: { label: 'Access request', icon: 'pi-key', tone: 'primary' },
  benchmark_result_ready: { label: 'Benchmark ready', icon: 'pi-chart-bar', tone: 'primary' },
  calibration_failed: { label: 'Calibration failed', icon: 'pi-exclamation-triangle', tone: 'error' },
};

const FALLBACK_META: NotificationTypeMeta = { label: 'Notification', icon: 'pi-bell', tone: 'primary' };

export function notificationMeta(type: string): NotificationTypeMeta {
  return NOTIFICATION_TYPE_META[type] ?? FALLBACK_META;
}

/** `wss://host/api/ws/notifications?token=…` on the page's own origin. */
export function buildNotificationWsUrl(token: string): string {
  const loc = typeof window !== 'undefined' ? window.location : undefined;
  const origin = loc ? `${loc.protocol === 'https:' ? 'wss:' : 'ws:'}//${loc.host}` : '';
  return `${origin}/api/ws/notifications?token=${encodeURIComponent(token)}`;
}

const POLL_INTERVAL_MS = 60_000;
const MAX_BACKOFF_MS = 60_000;
const KEEPALIVE_MS = 25_000;

/**
 * The user's notifications: inbox reads and read markers over REST, plus a
 * live socket that announces new items as they are published.
 *
 * The REST endpoints are the record — the socket only says "something new
 * arrived". So a dropped socket costs nothing: every (re)connect re-reads the
 * unread count, and a slow poll keeps the badge honest while the socket is
 * down. Components subscribe to `latest` for pushed items and read
 * `unreadCount` for the badge; both are shared, so the bell and the inbox
 * page never disagree.
 */
@Injectable({ providedIn: 'root' })
export class NotificationService {
  private http = inject(HttpClient);
  private auth = inject(AuthService);

  /** Unread items addressed to the caller. */
  readonly unreadCount = signal(0);
  /** The most recently pushed item, for components that react to arrivals. */
  readonly latest = signal<AppNotification | null>(null);
  /** Whether the live socket is currently open. */
  readonly live = signal(false);

  private ws: WebSocket | null = null;
  private active = false;
  private backoff = 2_000;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private pollTimer: ReturnType<typeof setInterval> | null = null;
  private keepaliveTimer: ReturnType<typeof setInterval> | null = null;
  /**
   * Bumped by every count read. Only the newest read may set the badge, so a
   * slow response cannot overwrite a later push or read.
   */
  private countGeneration = 0;
  /** Reads in flight, by id: a second click joins the first request. */
  private pendingReads = new Map<number, Promise<void>>();

  list(opts: { unreadOnly?: boolean; page?: number; size?: number } = {}): Promise<NotificationPage> {
    const params = new HttpParams()
      .set('unreadOnly', String(opts.unreadOnly ?? false))
      .set('page', String(opts.page ?? 0))
      .set('size', String(opts.size ?? 20));
    return firstValueFrom(this.http.get<NotificationPage>('/api/me/notifications', { params }));
  }

  /** Read the unread count from the server; the newest read wins. */
  async refreshUnreadCount(): Promise<void> {
    const generation = ++this.countGeneration;
    try {
      const count = await firstValueFrom(this.http.get<number>('/api/me/notifications/unread-count'));
      if (generation === this.countGeneration) this.unreadCount.set(count);
    } catch {
      // Keep the last known count; the next poll, change, or reconnect retries.
    }
  }

  /**
   * Show a change at once, then confirm it from the server. The refresh also
   * invalidates any count read already in flight, which was computed before
   * this change and would otherwise overwrite it.
   */
  private adjustUnreadCount(update: (n: number) => number): void {
    this.unreadCount.update((n) => Math.max(0, update(n)));
    void this.refreshUnreadCount();
  }

  markRead(notification: AppNotification): Promise<void> {
    if (notification.read) return Promise.resolve();
    const pending = this.pendingReads.get(notification.id);
    if (pending) return pending;
    const request = firstValueFrom(this.http.post<void>(`/api/me/notifications/${notification.id}/read`, {}))
      .then(() => {
        notification.read = true;
        this.adjustUnreadCount((n) => n - 1);
      })
      .finally(() => this.pendingReads.delete(notification.id));
    this.pendingReads.set(notification.id, request);
    return request;
  }

  async markAllRead(): Promise<void> {
    await firstValueFrom(this.http.post<void>('/api/me/notifications/read-all', {}));
    // Something published after the server's statement is still unread, so
    // the server count, not a hard zero, is the truth.
    this.adjustUnreadCount(() => 0);
  }

  /** Start live updates. Idempotent; the shell calls it once per session. */
  start(): void {
    if (this.active) return;
    this.active = true;
    void this.refreshUnreadCount();
    this.pollTimer = setInterval(() => {
      if (!this.live()) void this.refreshUnreadCount();
    }, POLL_INTERVAL_MS);
    void this.connect();
  }

  stop(): void {
    this.active = false;
    if (this.pollTimer) clearInterval(this.pollTimer);
    if (this.reconnectTimer) clearTimeout(this.reconnectTimer);
    if (this.keepaliveTimer) clearInterval(this.keepaliveTimer);
    this.pollTimer = this.reconnectTimer = this.keepaliveTimer = null;
    this.ws?.close();
    this.ws = null;
    this.live.set(false);
  }

  private async connect(): Promise<void> {
    if (!this.active || typeof WebSocket === 'undefined') return;
    const token = await this.auth.freshToken();
    if (!this.active) return;
    if (!token) {
      this.scheduleReconnect();
      return;
    }
    const ws = new WebSocket(buildNotificationWsUrl(token));
    this.ws = ws;

    ws.onopen = () => {
      this.backoff = 2_000;
      this.live.set(true);
      // Anything published while the socket was down is in the count.
      void this.refreshUnreadCount();
      this.keepaliveTimer = setInterval(() => {
        if (ws.readyState === WebSocket.OPEN) ws.send('{"action":"ping"}');
      }, KEEPALIVE_MS);
    };

    ws.onmessage = (event: MessageEvent) => {
      try {
        const msg = JSON.parse(event.data);
        if (msg?.event === 'notification' && msg.notification) {
          this.latest.set(msg.notification as AppNotification);
          this.adjustUnreadCount((n) => n + 1);
        }
      } catch {
        // Ignore frames this client does not understand.
      }
    };

    ws.onclose = () => {
      if (this.keepaliveTimer) clearInterval(this.keepaliveTimer);
      this.keepaliveTimer = null;
      if (this.ws === ws) this.ws = null;
      this.live.set(false);
      this.scheduleReconnect();
    };
  }

  private scheduleReconnect(): void {
    if (!this.active || this.reconnectTimer) return;
    const delay = this.backoff;
    this.backoff = Math.min(this.backoff * 2, MAX_BACKOFF_MS);
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null;
      void this.connect();
    }, delay);
  }
}
