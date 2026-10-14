import {
  ChangeDetectionStrategy,
  Component,
  ElementRef,
  HostListener,
  OnDestroy,
  OnInit,
  effect,
  inject,
  signal,
  untracked,
} from '@angular/core';
import {
  AppNotification,
  NotificationService,
  notificationMeta,
} from '../../../core/services/notification.service';
import { formatRelativeTime } from '../../utils/date';

const PAGE_SIZE = 15;
/** Start loading the next page this close (px) to the end of the list. */
const LOAD_MORE_THRESHOLD_PX = 80;

/**
 * The bell in the top bar and its popover — the only place notifications are
 * shown. Badge with the unread count; the popover lists everything addressed
 * to the user, newest first, with an All/Unread filter, click-to-read, "mark
 * all as read", and older items loaded as the list is scrolled. Items pushed
 * over the live socket appear at the top while it is open.
 *
 * It lives in the shell, so it owns the notification service's live
 * connection for the whole session.
 */
@Component({
  selector: 'app-notification-bell',
  standalone: true,
  templateUrl: './notification-bell.html',
  styleUrl: './notification-bell.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class NotificationBell implements OnInit, OnDestroy {
  notifications = inject(NotificationService);
  private host = inject(ElementRef<HTMLElement>);

  open = signal(false);
  unreadOnly = signal(false);
  items = signal<AppNotification[]>([]);
  loading = signal(false);
  hasMore = signal(false);
  error = signal<string | null>(null);
  /** Pages already shown; the next fetch asks for this one. */
  private page = 0;
  /**
   * Bumped by every reload. A response from an older generation (a filter
   * switched while it was in flight) is dropped instead of mixed in.
   */
  private generation = 0;

  readonly meta = notificationMeta;
  readonly age = formatRelativeTime;

  constructor() {
    effect(() => {
      const pushed = this.notifications.latest();
      if (!pushed) return;
      untracked(() => {
        if (this.items().some((n) => n.id === pushed.id)) return;
        this.items.update((list) => [pushed, ...list]);
      });
    });
  }

  ngOnInit(): void {
    this.notifications.start();
  }

  ngOnDestroy(): void {
    this.notifications.stop();
  }

  badgeLabel(): string {
    const n = this.notifications.unreadCount();
    return n > 99 ? '99+' : String(n);
  }

  async toggle(): Promise<void> {
    if (this.open()) {
      this.open.set(false);
      return;
    }
    this.open.set(true);
    await this.reload();
  }

  async setFilter(unreadOnly: boolean): Promise<void> {
    if (this.unreadOnly() === unreadOnly) return;
    this.unreadOnly.set(unreadOnly);
    await this.reload();
  }

  async reload(): Promise<void> {
    this.generation++;
    this.page = 0;
    this.items.set([]);
    this.hasMore.set(false);
    this.loading.set(false);
    await this.fetch();
  }

  onScroll(event: Event): void {
    const el = event.target as HTMLElement;
    if (el.scrollHeight - el.scrollTop - el.clientHeight < LOAD_MORE_THRESHOLD_PX) {
      void this.loadMore();
    }
  }

  async loadMore(): Promise<void> {
    if (this.loading() || !this.hasMore()) return;
    await this.fetch();
  }

  private async fetch(): Promise<void> {
    const generation = this.generation;
    const page = this.page;
    this.loading.set(true);
    this.error.set(null);
    try {
      const result = await this.notifications.list({
        unreadOnly: this.unreadOnly(),
        page,
        size: PAGE_SIZE,
      });
      if (generation !== this.generation) return;
      const known = new Set(this.items().map((n) => n.id));
      this.items.update((list) => [...list, ...result.content.filter((n) => !known.has(n.id))]);
      this.hasMore.set(!result.last);
      // Only a page that arrived moves the cursor; a failed one is retried.
      this.page = page + 1;
    } catch {
      if (generation === this.generation) this.error.set('Could not load notifications.');
    } finally {
      if (generation === this.generation) this.loading.set(false);
    }
  }

  async markRead(item: AppNotification): Promise<void> {
    if (item.read) return;
    try {
      await this.notifications.markRead(item);
    } catch {
      this.error.set('Could not mark the notification as read.');
      return;
    }
    if (this.unreadOnly()) {
      // The server's unread set just shrank, so page offsets moved: re-read
      // from the top rather than skip an item on the next page.
      await this.reload();
    } else {
      this.items.update((list) => list.map((n) => (n.id === item.id ? { ...n, read: true } : n)));
    }
  }

  async markAllRead(): Promise<void> {
    try {
      await this.notifications.markAllRead();
    } catch {
      this.error.set('Could not mark notifications as read.');
      return;
    }
    // A fresh read of the current filter discards any page still in flight
    // and resets loading and paging together.
    await this.reload();
  }

  @HostListener('document:click', ['$event'])
  onDocumentClick(event: MouseEvent): void {
    if (this.open() && !this.host.nativeElement.contains(event.target as Node)) {
      this.open.set(false);
    }
  }

  @HostListener('document:keydown.escape')
  onEscape(): void {
    this.open.set(false);
  }
}
