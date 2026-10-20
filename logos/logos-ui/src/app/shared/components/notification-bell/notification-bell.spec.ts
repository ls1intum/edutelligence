import { signal } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';

import { AppNotification, NotificationService } from '../../../core/services/notification.service';
import { NotificationBell } from './notification-bell';

/**
 * The popover's behaviour against a fake service: opening loads the first
 * page, the filter reloads, clicking an item marks it read, scrolling to the
 * end fetches older items, and a pushed item appears at the top.
 */

const item = (id: number, read = false): AppNotification => ({
  id,
  type: 'batch_job_finished',
  title: `Item ${id}`,
  body: null,
  payload: null,
  source: 'webservice',
  actor_user_id: null,
  created_at: '2026-10-14T10:00:00Z',
  read,
});

class FakeNotificationService {
  unreadCount = signal(2);
  latest = signal<AppNotification | null>(null);
  start = vi.fn();
  stop = vi.fn();
  list = vi.fn();
  markRead = vi.fn().mockImplementation(async (n: AppNotification) => {
    n.read = true;
    this.unreadCount.update((c) => c - 1);
  });
  markAllRead = vi.fn().mockImplementation(async () => this.unreadCount.set(0));
}

describe('NotificationBell', () => {
  let fixture: ComponentFixture<NotificationBell>;
  let bell: NotificationBell;
  let service: FakeNotificationService;

  beforeEach(async () => {
    service = new FakeNotificationService();
    service.list.mockResolvedValue({ content: [item(2), item(1, true)], total_elements: 2, total_pages: 1, number: 0, last: true });
    await TestBed.configureTestingModule({
      imports: [NotificationBell],
      providers: [{ provide: NotificationService, useValue: service }],
    }).compileComponents();
    fixture = TestBed.createComponent(NotificationBell);
    bell = fixture.componentInstance;
    fixture.detectChanges();
  });

  it('starts the live connection with the shell and stops it with it', () => {
    expect(service.start).toHaveBeenCalled();
    fixture.destroy();
    expect(service.stop).toHaveBeenCalled();
  });

  it('shows the unread count on the badge, capped at 99+', () => {
    expect(fixture.nativeElement.querySelector('.bell__badge').textContent.trim()).toBe('2');
    service.unreadCount.set(140);
    fixture.detectChanges();
    expect(fixture.nativeElement.querySelector('.bell__badge').textContent.trim()).toBe('99+');
  });

  it('loads the first page when opened', async () => {
    await bell.toggle();
    fixture.detectChanges();
    expect(service.list).toHaveBeenCalledWith({ unreadOnly: false, page: 0, size: 15 });
    expect(fixture.nativeElement.querySelectorAll('.item').length).toBe(2);
    expect(fixture.nativeElement.querySelectorAll('.item--unread').length).toBe(1);
  });

  it('reloads with the unread filter', async () => {
    await bell.toggle();
    await bell.setFilter(true);
    expect(service.list).toHaveBeenLastCalledWith({ unreadOnly: true, page: 0, size: 15 });
  });

  it('marks a clicked item read', async () => {
    await bell.toggle();
    await bell.markRead(bell.items()[0]);
    expect(service.markRead).toHaveBeenCalled();
    expect(bell.items()[0].read).toBe(true);
  });

  it('fetches the next page when scrolled to the end, and only then', async () => {
    service.list.mockResolvedValueOnce({ content: [item(3)], total_elements: 2, total_pages: 2, number: 0, last: false });
    await bell.toggle();
    service.list.mockResolvedValueOnce({ content: [item(4, true)], total_elements: 2, total_pages: 2, number: 1, last: true });

    bell.onScroll({ target: { scrollHeight: 1000, scrollTop: 0, clientHeight: 400 } } as unknown as Event);
    expect(service.list).toHaveBeenCalledTimes(1);

    bell.onScroll({ target: { scrollHeight: 1000, scrollTop: 560, clientHeight: 400 } } as unknown as Event);
    await vi.waitFor(() => expect(bell.items().map((n) => n.id)).toEqual([3, 4]));
    expect(service.list).toHaveBeenLastCalledWith({ unreadOnly: false, page: 1, size: 15 });
  });

  it('drops a response from a filter the user already left', async () => {
    let resolveAll!: (page: unknown) => void;
    service.list.mockReturnValueOnce(new Promise((r) => (resolveAll = r)));
    const opening = bell.toggle();
    service.list.mockResolvedValueOnce({ content: [item(2)], total_elements: 1, total_pages: 1, number: 0, last: true });
    await bell.setFilter(true);
    resolveAll({ content: [item(1, true), item(5, true)], total_elements: 2, total_pages: 2, number: 0, last: false });
    await opening;

    expect(bell.items().map((n) => n.id)).toEqual([2]);
    expect(bell.hasMore()).toBe(false);
  });

  it('retries the same page after a failed load', async () => {
    service.list.mockResolvedValueOnce({ content: [item(3)], total_elements: 2, total_pages: 2, number: 0, last: false });
    await bell.toggle();
    service.list.mockRejectedValueOnce(new Error('offline'));
    await bell.loadMore();
    expect(bell.error()).not.toBeNull();

    service.list.mockResolvedValueOnce({ content: [item(4)], total_elements: 2, total_pages: 2, number: 1, last: true });
    await bell.loadMore();
    expect(service.list).toHaveBeenNthCalledWith(2, { unreadOnly: false, page: 1, size: 15 });
    expect(service.list).toHaveBeenNthCalledWith(3, { unreadOnly: false, page: 1, size: 15 });
    expect(bell.items().map((n) => n.id)).toEqual([3, 4]);
  });

  it('re-reads the unread view from the top after an item is read', async () => {
    const firstPage = Array.from({ length: 15 }, (_, i) => item(100 - i));
    service.list.mockResolvedValueOnce({ content: firstPage, total_elements: 30, total_pages: 2, number: 0, last: false });
    await bell.toggle();
    service.list.mockResolvedValueOnce({ content: firstPage, total_elements: 30, total_pages: 2, number: 0, last: false });
    await bell.setFilter(true);

    // Reading one item shrinks the server's unread set: page 1 would now skip
    // the old 16th item, so the view reloads from page 0 without the read one.
    service.list.mockResolvedValueOnce({ content: firstPage.slice(1), total_elements: 29, total_pages: 2, number: 0, last: false });
    await bell.markRead(bell.items()[0]);

    expect(service.list).toHaveBeenLastCalledWith({ unreadOnly: true, page: 0, size: 15 });
    expect(bell.items().map((n) => n.id)).not.toContain(100);
  });

  it('prepends a pushed item once', async () => {
    await bell.toggle();
    service.latest.set(item(9));
    fixture.detectChanges();
    service.latest.set(item(9));
    fixture.detectChanges();
    expect(bell.items().map((n) => n.id)).toEqual([9, 2, 1]);
  });

  it('marks all read and empties the unread view', async () => {
    await bell.toggle();
    await bell.setFilter(true);
    service.list.mockResolvedValueOnce({ content: [], total_elements: 0, total_pages: 0, number: 0, last: true });
    await bell.markAllRead();
    expect(service.unreadCount()).toBe(0);
    expect(bell.items()).toEqual([]);
    expect(bell.loading()).toBe(false);
  });

  for (const unreadOnly of [false, true]) {
    it(`discards a page still loading when all are marked read (${unreadOnly ? 'Unread' : 'All'})`, async () => {
      service.list.mockResolvedValueOnce({ content: [item(3)], total_elements: 2, total_pages: 2, number: 0, last: false });
      await bell.toggle();
      if (unreadOnly) {
        service.list.mockResolvedValueOnce({ content: [item(3)], total_elements: 2, total_pages: 2, number: 0, last: false });
        await bell.setFilter(true);
      }
      let resolveOld!: (page: unknown) => void;
      service.list.mockReturnValueOnce(new Promise((r) => (resolveOld = r)));
      const olderPage = bell.loadMore();

      const afterMarkAll = unreadOnly ? [] : [item(3, true), item(4, true)];
      service.list.mockResolvedValueOnce({ content: afterMarkAll, total_elements: afterMarkAll.length, total_pages: 1, number: 0, last: true });
      await bell.markAllRead();
      resolveOld({ content: [item(4)], total_elements: 2, total_pages: 2, number: 1, last: true });
      await olderPage;

      expect(bell.items().filter((n) => !n.read)).toEqual([]);
      expect(bell.loading()).toBe(false);
    });
  }
});
