import {
  Component,
  Input,
  OnChanges,
  OnDestroy,
  inject,
  signal,
  computed,
  SimpleChanges,
  ChangeDetectionStrategy,
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { formatUsd } from '../../../../shared/utils/currency';
import { StatisticsService } from '../../services/statistics.service';
import { RequestItem } from '../../statistics.models';
import { StatsSkeletonComponent } from '../skeletons/skeletons';
import {
  deriveStage,
  getRequestBorderColor,
  formatTimeAgo,
  formatElapsed,
  RequestStage,
} from '../../statistics.utils';

/**
 * Rows the websocket pushes, and the page size of one "load older" step. Must
 * stay in sync with `RequestLogService.LATEST_REQUESTS_PAGE_SIZE`.
 */
const PAGE_SIZE = 10;

@Component({
  selector: 'app-stats-recent-requests',
  standalone: true,
  imports: [CommonModule, StatsSkeletonComponent],
  templateUrl: './recent-requests.html',
  changeDetection: ChangeDetectionStrategy.Eager,
  styleUrl: './recent-requests.scss',
})
export class RecentRequests implements OnChanges, OnDestroy {
  private statisticsService = inject(StatisticsService);

  /** Live rows pushed by the stats WS (already scoped to the selected time range). */
  @Input() liveRequests: RequestItem[] = [];

  /**
   * How many requests the selected range holds, taken from the statistics
   * totals. It is the same range, resolved once per range change, so during a
   * live session it can trail the live rows by a few — hence the floor in
   * `totalCount()`.
   */
  @Input() totalInRange = 0;

  /** The selected range as ISO strings — what "load older" pages through. */
  @Input() range: { startIso: string; endIso: string } | null = null;

  /** True while a range change is in flight and the rows below are stale. */
  @Input() pending = false;

  /** Shared ticker: ms since epoch, updated by setInterval. */
  now = signal(Date.now());

  private intervalId: ReturnType<typeof setInterval> | null = null;

  // Input mirror signals so the computed()s below actually react: a plain
  // @Input() is not a tracked producer, so reading it inside computed() would
  // cache the very first value (an empty list) forever.
  private readonly _liveRequests = signal<RequestItem[]>([]);
  private readonly _totalInRange = signal(0);

  /** Pages fetched on demand, oldest step last. Cleared when the range moves. */
  private readonly _olderRequests = signal<RequestItem[]>([]);
  readonly loadingOlder = signal(false);
  readonly olderError = signal<string | null>(null);
  /**
   * What the last fetched page reported about further rows — authoritative,
   * unlike comparing against a count that can trail the live feed. Null until
   * a page has been fetched.
   */
  private readonly _serverHasMore = signal<boolean | null>(null);
  /**
   * Range count as the paging endpoint counted it. Preferred over the input
   * once present: it is counted at fetch time over the very same range, while
   * the statistics totals are resolved once per range change.
   */
  private readonly _pageTotal = signal<number | null>(null);

  /**
   * Live rows first, then the fetched history, de-duplicated by request id.
   *
   * The live push always carries the newest page, so a row appearing in both
   * takes its state from there: an older page is a snapshot and would show a
   * request that has since finished as still running.
   */
  readonly displayItems = computed<RequestItem[]>(() => {
    const live = this._liveRequests();
    const seen = new Set(live.map((r) => r.request_id));
    const older = this._olderRequests().filter((r) => !seen.has(r.request_id));
    return [...live, ...older];
  });

  readonly shownCount = computed(() => this.displayItems().length);

  /** The range total, floored at what is on screen (the push can lag a page). */
  readonly totalCount = computed(() =>
    Math.max(this._pageTotal() ?? this._totalInRange(), this.shownCount()),
  );

  readonly hasMore = computed(() => {
    const reported = this._serverHasMore();
    if (reported !== null) return reported;
    return this.shownCount() < this.totalCount();
  });

  private hasLive = computed(() =>
    this.displayItems().some((it) => deriveStage(it) !== 'complete'),
  );

  ngOnChanges(changes: SimpleChanges): void {
    if (changes['liveRequests']) this._liveRequests.set(this.liveRequests ?? []);
    if (changes['totalInRange']) this._totalInRange.set(this.totalInRange ?? 0);
    // A new range invalidates every page fetched for the previous one.
    if (changes['range'] && !changes['range'].firstChange) this.resetOlder();
    // Re-schedule ticker whenever inputs change so cadence stays correct.
    this.scheduleTicker();
  }

  ngOnDestroy(): void {
    this.clearTicker();
  }

  private resetOlder(): void {
    this._olderRequests.set([]);
    this._serverHasMore.set(null);
    this._pageTotal.set(null);
    this.olderError.set(null);
    this.loadingOlder.set(false);
  }

  /**
   * Fetch the next page of older requests.
   *
   * Offsets are counted from the newest row, so requests arriving while pages
   * are open shift the window and the next page overlaps what is already shown
   * — which the de-duplication in `displayItems` absorbs. Overlapping is the
   * safe direction: the alternative (a timestamp cursor) would have to guess
   * which of the three timestamps the range predicate coalesced.
   */
  async loadOlder(): Promise<void> {
    const range = this.range;
    if (!range || this.loadingOlder() || !this.hasMore()) return;

    this.loadingOlder.set(true);
    this.olderError.set(null);
    const offset = this.shownCount();
    try {
      const page = await this.statisticsService.getLatestRequests(
        range.startIso,
        range.endIso,
        PAGE_SIZE,
        offset,
      );
      this._olderRequests.update((current) => [...current, ...(page.requests ?? [])]);
      if (typeof page.total === 'number') this._pageTotal.set(page.total);
      this._serverHasMore.set(page.has_more === true);
    } catch (err: unknown) {
      const e = err as { status?: number; error?: { error?: string; detail?: string } };
      const detail = e.error?.error ?? e.error?.detail ?? `HTTP ${e.status}`;
      this.olderError.set(`Could not load older requests: ${detail}`);
    } finally {
      this.loadingOlder.set(false);
    }
  }

  private scheduleTicker(): void {
    this.clearTicker();
    const cadence = this.hasLive() ? 1000 : 10_000;
    this.intervalId = setInterval(() => this.now.set(Date.now()), cadence);
  }

  private clearTicker(): void {
    if (this.intervalId !== null) {
      clearInterval(this.intervalId);
      this.intervalId = null;
    }
  }

  // ── Template helpers ─────────────────────────────────────────────────────

  stageOf(item: RequestItem): RequestStage {
    return deriveStage(item);
  }

  borderColorOf(item: RequestItem): string {
    return getRequestBorderColor(deriveStage(item), item.status);
  }

  bgTintOf(item: RequestItem): string {
    const color = getRequestBorderColor(deriveStage(item), item.status);
    // wrap with low-opacity version for tinted background
    return color.replace('))', ') / 0.07)');
  }

  timeAgoOf(item: RequestItem): string {
    return formatTimeAgo(item.enqueue_ts ?? item.timestamp, this.now());
  }

  /** Full name ("First Last"), falling back to the username. */
  requesterOf(item: RequestItem): string {
    return item.full_name || item.username || '';
  }

  /** Cloud cost in USD; null when no price is on record for the model. */
  costLabelOf(item: RequestItem): string | null {
    if (item.cost_microcents == null) return null;
    return formatUsd(item.cost_microcents);
  }

  /** Token line "↑prompt ↓completion", only when token counts are known. */
  tokensLabelOf(item: RequestItem): string | null {
    const p = item.prompt_tokens;
    const c = item.completion_tokens;
    if (p == null && c == null) return null;
    return `↑${p ?? 0} ↓${c ?? 0}`;
  }

  totalTimeLabelOf(item: RequestItem): string {
    const stage = deriveStage(item);
    if (stage === 'complete' && item.total_seconds != null) {
      return `${item.total_seconds.toFixed(2)}s`;
    }
    if (item.enqueue_ts) {
      return formatElapsed((this.now() - new Date(item.enqueue_ts).getTime()) / 1000);
    }
    return '...';
  }

  elapsedOf(item: RequestItem): string {
    if (!item.scheduled_ts) return '0.0s';
    return formatElapsed((this.now() - new Date(item.scheduled_ts).getTime()) / 1000);
  }

  errorSnippet(msg: string | null): string {
    if (!msg) return '';
    return msg.length > 60 ? msg.slice(0, 60) + '...' : msg;
  }

  formatCount(v: number): string {
    return v.toLocaleString();
  }

  trackById(_: number, item: RequestItem): string {
    return item.request_id;
  }
}
