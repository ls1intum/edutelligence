import { TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';

import { AuthService } from '../auth/services/auth.service';
import {
  AppNotification,
  NotificationService,
  buildNotificationWsUrl,
  notificationMeta,
} from './notification.service';

/**
 * The inbox calls and the shared unread count the bell's badge reads. The
 * live socket is not opened here (`start()` is not called).
 */

const item = (overrides: Partial<AppNotification> = {}): AppNotification => ({
  id: 7,
  type: 'budget_hit',
  title: 'Budget hit',
  body: null,
  payload: null,
  source: 'webservice',
  actor_user_id: null,
  created_at: '2026-10-14T10:00:00Z',
  read: false,
  ...overrides,
});

describe('NotificationService', () => {
  let service: NotificationService;
  let http: HttpTestingController;

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        { provide: AuthService, useValue: { freshToken: vi.fn().mockResolvedValue('t') } },
      ],
    });
    service = TestBed.inject(NotificationService);
    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => http.verify());

  it('lists the inbox with filter and paging parameters', async () => {
    const pending = service.list({ unreadOnly: true, page: 2, size: 15 });
    const req = http.expectOne((r) => r.url === '/api/me/notifications');
    expect(req.request.params.get('unreadOnly')).toBe('true');
    expect(req.request.params.get('page')).toBe('2');
    expect(req.request.params.get('size')).toBe('15');
    req.flush({ content: [item()], total_elements: 1, total_pages: 1, number: 2, last: true });
    expect((await pending).content[0].id).toBe(7);
  });

  it('reads the unread count into the shared signal', async () => {
    const pending = service.refreshUnreadCount();
    http.expectOne('/api/me/notifications/unread-count').flush(4);
    await pending;
    expect(service.unreadCount()).toBe(4);
  });

  const COUNT_URL = '/api/me/notifications/unread-count';

  it('marks one item read, lowers the count, then confirms it from the server', async () => {
    service.unreadCount.set(2);
    const unread = item();
    const pending = service.markRead(unread);
    http.expectOne({ method: 'POST', url: '/api/me/notifications/7/read' }).flush(null);
    await pending;
    expect(unread.read).toBe(true);
    expect(service.unreadCount()).toBe(1);
    http.expectOne(COUNT_URL).flush(1);
  });

  it('sends one request for two clicks on the same unread item', async () => {
    service.unreadCount.set(2);
    const unread = item();
    const first = service.markRead(unread);
    const second = service.markRead(unread);
    http.expectOne({ method: 'POST', url: '/api/me/notifications/7/read' }).flush(null);
    await Promise.all([first, second]);
    expect(service.unreadCount()).toBe(1);
    http.expectOne(COUNT_URL).flush(1);
  });

  it('ignores a count response that a later change already superseded', async () => {
    // The reconnect read starts, computed before the push arrives.
    const reconnect = service.refreshUnreadCount();
    const stale = http.expectOne(COUNT_URL);
    // A push arrives: badge +1 and a newer confirmation read.
    (service as unknown as { adjustUnreadCount(f: (n: number) => number): void }).adjustUnreadCount((n) => n + 1);
    const fresh = http.match(COUNT_URL).find((r) => r !== stale)!;
    fresh.flush(1);
    stale.flush(0);
    await reconnect;
    await Promise.resolve();
    expect(service.unreadCount()).toBe(1);
  });

  it('does not call the server for an item that is already read', async () => {
    await service.markRead(item({ read: true }));
    http.expectNone('/api/me/notifications/7/read');
  });

  it('marks everything read, then takes the server count (an item published meanwhile)', async () => {
    service.unreadCount.set(5);
    const pending = service.markAllRead();
    http.expectOne({ method: 'POST', url: '/api/me/notifications/read-all' }).flush(null);
    await pending;
    expect(service.unreadCount()).toBe(0);
    http.expectOne(COUNT_URL).flush(1);
    await Promise.resolve();
    expect(service.unreadCount()).toBe(1);
  });

  it('builds the socket URL on the page origin and encodes the token', () => {
    expect(buildNotificationWsUrl('a b')).toMatch(/^wss?:\/\/[^/]+\/api\/ws\/notifications\?token=a%20b$/);
  });

  it('falls back to a generic look for types it does not know', () => {
    expect(notificationMeta('budget_hit').icon).toBe('pi-wallet');
    expect(notificationMeta('something_new')).toEqual({ label: 'Notification', icon: 'pi-bell', tone: 'primary' });
  });
});
