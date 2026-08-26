import {
  ChangeDetectionStrategy,
  Component,
  Input,
  OnChanges,
  OnDestroy,
  SimpleChanges,
  computed,
  inject,
  signal,
} from '@angular/core';
import { CommonModule } from '@angular/common';

import { AppSelectOption, SelectComponent } from '../../../../shared/components/select/select';
import { RequestItem } from '../../../statistics/statistics.models';
import { deriveStage, formatTimeAgo } from '../../../statistics/statistics.utils';
import { TeamActivityService } from './activity-tab.service';
import { RequestCursor, TeamActivityPayload } from './activity-tab.models';

/** How often the live counts are refreshed while the tab is open. */
const REFRESH_MS = 5_000;

/** Windows offered for the usage figures. */
const DAY_OPTIONS: AppSelectOption[] = [
  { value: '1', label: 'Last 24 hours' },
  { value: '7', label: 'Last 7 days' },
  { value: '30', label: 'Last 30 days' },
  { value: '90', label: 'Last 90 days' },
];

/**
 * What this team is running right now, what it has used, and the requests
 * behind both (issue #776).
 *
 * Sits next to Cloud Usage, which answers the same period in money: that tab
 * is what the cloud providers billed, this one is what the platform did. A
 * local model costs nothing and still consumes the cluster, so neither view
 * substitutes for the other.
 */
@Component({
  selector: 'app-activity-tab',
  standalone: true,
  imports: [CommonModule, SelectComponent],
  templateUrl: './activity-tab.html',
  changeDetection: ChangeDetectionStrategy.Eager,
  styleUrl: './activity-tab.scss',
})
export class ActivityTabComponent implements OnChanges, OnDestroy {
  @Input() teamId = 0;

  private activityService = inject(TeamActivityService);

  readonly days = signal(7);
  readonly filterUserId = signal<number | null>(null);
  readonly activity = signal<TeamActivityPayload | null>(null);
  readonly loading = signal(true);
  readonly error = signal<string | null>(null);

  readonly dayOptions = DAY_OPTIONS;

  /**
   * Cursor of each page already visited. Page 0 is always null (start at the
   * newest); going back is a pop rather than a reverse query, because a keyset
   * cursor only points forwards.
   */
  private cursorForPage: (RequestCursor | null)[] = [null];
  readonly pageIndex = signal(0);

  /**
   * How many loads are in flight, and the number of the newest one. The pager
   * only moves while none is in flight, and a load may only apply its answer
   * while it is still the newest: with a page still loading, a click used to
   * advance the index on the strength of the previous page's answer — its
   * `has_more` flag and next cursor both pointed at the page behind — walking
   * past the last page (issue #799).
   */
  private loadsInFlight = signal(0);
  private loadSeq = 0;

  private timer: ReturnType<typeof setInterval> | null = null;

  readonly selectedDaysValue = computed(() => String(this.days()));

  readonly requesterOptions = computed<AppSelectOption[]>(() => [
    { value: '', label: 'Everyone in this team' },
    ...(this.activity()?.requesters ?? []).map((r) => ({
      value: String(r.id),
      // The count is what tells the reader which entries are worth opening.
      label: `${r.label} (${r.requestCount.toLocaleString()})`,
    })),
  ]);

  readonly selectedRequesterValue = computed(() => {
    const id = this.filterUserId();
    return id === null ? '' : String(id);
  });

  readonly requests = computed<RequestItem[]>(() => this.activity()?.requests ?? []);

  readonly hasPrev = computed(() => this.pageIndex() > 0);
  readonly hasNext = computed(() => !!this.activity()?.requests_has_more);

  /**
   * A page load is in flight. The pager buttons wait for it to land: while
   * the answer is out, the page on screen is not the newest one, so neither
   * its `has_more` flag nor its next cursor may be acted on (issue #799).
   */
  readonly pageLoadInFlight = computed(() => this.loadsInFlight() > 0);

  /** 1-based number of the first row on this page, for the "21-40 of n" line. */
  readonly firstRowNumber = computed(() =>
    this.requests().length === 0 ? 0 : this.pageIndex() * 20 + 1,
  );

  readonly lastRowNumber = computed(
    () => this.firstRowNumber() + Math.max(0, this.requests().length - 1),
  );

  readonly failureRate = computed(() => {
    const live = this.activity()?.live;
    if (!live || live.finished === 0) return null;
    return (live.failed / live.finished) * 100;
  });

  /** In flight right now — the number the live counts exist for. */
  readonly inFlight = computed(() => {
    const live = this.activity()?.live;
    return live ? live.queued + live.running : 0;
  });

  ngOnChanges(changes: SimpleChanges): void {
    if (changes['teamId'] && this.teamId) {
      this.resetToFirstPage();
      void this.load();
      this.startTimer();
    }
  }

  ngOnDestroy(): void {
    this.stopTimer();
  }

  setDays(value: string | null): void {
    const parsed = Number(value);
    if (!Number.isFinite(parsed) || parsed <= 0) return;
    this.days.set(parsed);
    // A different window is a different set of requests, so the pages cut out
    // of the old one no longer point anywhere.
    this.resetToFirstPage();
    void this.load();
  }

  setRequester(value: string | null): void {
    const id = value ? Number(value) : null;
    const next = Number.isFinite(id as number) ? id : null;
    if (next === this.filterUserId()) return;
    this.filterUserId.set(next);
    this.resetToFirstPage();
    void this.load();
  }

  async nextPage(): Promise<void> {
    const cursor = this.activity()?.requests_next_cursor ?? null;
    if (!cursor || !this.hasNext() || this.pageLoadInFlight()) return;
    const target = this.pageIndex() + 1;
    this.cursorForPage[target] = cursor;
    this.pageIndex.set(target);
    await this.load();
  }

  async prevPage(): Promise<void> {
    if (!this.hasPrev() || this.pageLoadInFlight()) return;
    this.pageIndex.set(this.pageIndex() - 1);
    await this.load();
  }

  // ── Rendering helpers ──────────────────────────────────────────────────────

  formatNumber(value: number | null | undefined): string {
    return typeof value === 'number' ? value.toLocaleString() : '—';
  }

  /** Token totals run to nine figures; the exact digit is never the question. */
  formatTokens(value: number | null | undefined): string {
    if (typeof value !== 'number' || value <= 0) return '0';
    if (value >= 1_000_000_000) return `${(value / 1_000_000_000).toFixed(1)}B`;
    if (value >= 1_000_000) return `${(value / 1_000_000).toFixed(1)}M`;
    if (value >= 1_000) return `${(value / 1_000).toFixed(1)}k`;
    return String(value);
  }

  keyLabel(keyName: string, environment: string | null): string {
    // "-" is the placeholder a key with no environment carries in the database.
    return environment && environment !== '-' ? `${keyName} · ${environment}` : keyName;
  }

  stageOf(item: RequestItem): string {
    return deriveStage(item);
  }

  ageOf(item: RequestItem): string {
    return formatTimeAgo(item.enqueue_ts ?? item.timestamp, Date.now());
  }

  durationOf(item: RequestItem): string {
    if (item.total_seconds != null) return `${item.total_seconds.toFixed(2)}s`;
    return '—';
  }

  tokensOf(item: RequestItem): string {
    const p = item.prompt_tokens;
    const c = item.completion_tokens;
    if (p == null && c == null) return '—';
    return `↑${p ?? 0} ↓${c ?? 0}`;
  }

  requesterOf(item: RequestItem): string {
    return item.full_name?.trim() || item.username || '—';
  }

  trackByRequestId(_index: number, item: RequestItem): string {
    return item.request_id;
  }

  // ── Loading ────────────────────────────────────────────────────────────────

  private startTimer(): void {
    this.stopTimer();
    // The live counts are the point, so they refresh on their own. The usage
    // figures and the request list come along: one call answers all three, and
    // a team's spend over days does not move fast enough to need its own
    // cadence.
    this.timer = setInterval(() => void this.load(), REFRESH_MS);
  }

  private stopTimer(): void {
    if (this.timer !== null) {
      clearInterval(this.timer);
      this.timer = null;
    }
  }

  private resetToFirstPage(): void {
    this.pageIndex.set(0);
    this.cursorForPage = [null];
  }

  private async load(): Promise<void> {
    if (!this.teamId) return;
    const seq = ++this.loadSeq;
    this.loadsInFlight.update((n) => n + 1);
    try {
      const payload = await this.activityService.getActivity(this.teamId, this.days(), {
        userId: this.filterUserId(),
        cursor: this.cursorForPage[this.pageIndex()] ?? null,
      });
      // A newer load has started while this one was out (a page turned, the
      // window or the filter changed, the timer re-fired). Its answer belongs
      // to the view we left: applying it would land old rows — and an old
      // `has_more` flag — on the new page, which is how the pager walked past
      // the last page (issue #799).
      if (seq !== this.loadSeq) return;
      this.activity.set(payload);
      this.error.set(null);
    } catch {
      if (seq !== this.loadSeq) return;
      // Keep whatever is on screen: this runs on a timer, and blanking the tab
      // over one failed poll would make a brief network blip look like an
      // outage.
      this.error.set('Could not refresh activity.');
    } finally {
      this.loadsInFlight.update((n) => n - 1);
      this.loading.set(false);
    }
  }
}
