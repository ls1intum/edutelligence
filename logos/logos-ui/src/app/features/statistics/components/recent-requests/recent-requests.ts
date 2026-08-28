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
import {
  LatestRequestsPage,
  RequestCursor,
  StatisticsService,
} from '../../services/statistics.service';
import { RequestItem } from '../../statistics.models';
import { StatsSkeletonComponent } from '../skeletons/skeletons';
import {
  deriveStage,
  getRequestBorderColor,
  formatTimeAgo,
  formatElapsed,
  providerLabel,
  RequestStage,
} from '../../statistics.utils';

/**
 * Rows per page. Must stay in sync with
 * `RequestLogService.LATEST_REQUESTS_PAGE_SIZE`, which is what the websocket
 * pushes — otherwise page 1 (the live rows) and every fetched page would be
 * sized differently and the "1-10 of n" count would skip or repeat numbers.
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

  /**
   * Live rows pushed by the stats WS — the newest page, already narrowed to the
   * page's scope, since the server applies it to the push itself.
   */
  @Input() liveRequests: RequestItem[] = [];

  /**
   * How many requests the selected range holds, from the statistics totals.
   * Same range, resolved per aggregate push, so it can trail the live rows by a
   * few — hence the floor in `totalCount()`. Only used while page 1 is showing
   * live rows; a fetched page brings its own count.
   */
  @Input() totalInRange = 0;

  /** The selected range as ISO strings — what the pages are cut out of. */
  @Input() range: { startIso: string; endIso: string } | null = null;

  /** True while a range change is in flight and the rows below are stale. */
  @Input() pending = false;

  /**
   * The page's scope, so deeper pages are fetched with the same narrowing the
   * live push already has. Owned by the statistics page — the dropdowns used to
   * live in this toolbar and moved out when the filter stopped applying to this
   * list alone.
   */
  @Input() filterUserId: number | null = null;
  @Input() filterTeamId: number | null = null;

  /** Shared ticker: ms since epoch, updated by setInterval. */
  now = signal(Date.now());

  private intervalId: ReturnType<typeof setInterval> | null = null;

  // Input mirror signals so the computed()s below actually react: a plain
  // @Input() is not a tracked producer, so reading it inside computed() would
  // cache the very first value (an empty list) forever.
  private readonly _liveRequests = signal<RequestItem[]>([]);
  private readonly _totalInRange = signal(0);
  private readonly _filterUserId = signal<number | null>(null);
  private readonly _filterTeamId = signal<number | null>(null);

  /** Only for the empty state, which reads differently once a filter is on. */
  readonly filterActive = computed(
    () => this._filterUserId() !== null || this._filterTeamId() !== null,
  );

  // ── Paging ─────────────────────────────────────────────────────────────────

  /** 0-based. Page 0 is the live feed; everything deeper is fetched. */
  readonly pageIndex = signal(0);

  /**
   * The cursor each page was fetched with, indexed by page. Page 0 is always
   * `null` (start at the newest). Going back is a pop rather than a reverse
   * query: a keyset cursor only points forwards, so the way back is the trail
   * of cursors already used.
   */
  private cursorForPage: (RequestCursor | null)[] = [null];

  private readonly _pageRows = signal<RequestItem[]>([]);
  private readonly _pageTotal = signal<number | null>(null);
  private readonly _pageHasMore = signal(false);
  private readonly _pageNextCursor = signal<RequestCursor | null>(null);
  readonly loading = signal(false);
  readonly error = signal<string | null>(null);

  /**
   * True while page 1 shows what the websocket pushes rather than a fetch.
   *
   * A filtered view used to be excluded here and served entirely over REST,
   * because the push was platform-wide and could not answer a narrowed
   * question. The server scopes the push itself now, so page 1 stays live
   * whatever the filter says.
   */
  readonly onLivePage = computed(() => this.pageIndex() === 0);

  readonly displayItems = computed<RequestItem[]>(() =>
    this.onLivePage() ? this._liveRequests() : this._pageRows(),
  );

  readonly totalCount = computed(() => {
    const known = this.onLivePage() ? this._totalInRange() : (this._pageTotal() ?? 0);
    // Never promise fewer rows than are on screen: on the live page the
    // aggregate push the total comes from can be a beat behind the feed.
    return Math.max(known, this.firstRowNumber() + this.displayItems().length - 1);
  });

  /** 1-based number of the first row on this page, for the "11-20 of n" line. */
  readonly firstRowNumber = computed(() =>
    this.displayItems().length === 0 ? 0 : this.pageIndex() * PAGE_SIZE + 1,
  );

  readonly lastRowNumber = computed(
    () => this.firstRowNumber() + Math.max(0, this.displayItems().length - 1),
  );

  readonly hasPrev = computed(() => this.pageIndex() > 0);

  readonly hasNext = computed(() => {
    if (this.loading()) return false;
    // A full live page may have more behind it — same rule the server applies to
    // a fetched page, which reports it outright.
    return this.onLivePage()
      ? this._liveRequests().length >= PAGE_SIZE
      : this._pageHasMore();
  });

  private hasLive = computed(() =>
    this.displayItems().some((it) => deriveStage(it) !== 'complete'),
  );

  ngOnChanges(changes: SimpleChanges): void {
    if (changes['liveRequests']) this._liveRequests.set(this.liveRequests ?? []);
    if (changes['totalInRange']) this._totalInRange.set(this.totalInRange ?? 0);
    if (changes['filterUserId']) this._filterUserId.set(this.filterUserId);
    if (changes['filterTeamId']) this._filterTeamId.set(this.filterTeamId);
    // A new range or a new scope invalidates every page cut out of the previous
    // one. No fetch follows: page 0 is the live feed either way, and the
    // websocket is already sending it for the new scope.
    const scopeChanged =
      (changes['filterUserId'] && !changes['filterUserId'].firstChange) ||
      (changes['filterTeamId'] && !changes['filterTeamId'].firstChange);
    if ((changes['range'] && !changes['range'].firstChange) || scopeChanged) {
      this.resetToFirstPage();
    }
    // Re-schedule ticker whenever inputs change so cadence stays correct.
    this.scheduleTicker();
  }

  ngOnDestroy(): void {
    this.clearTicker();
  }

  private resetToFirstPage(): void {
    this.pageIndex.set(0);
    this.cursorForPage = [null];
    this._pageRows.set([]);
    this._pageTotal.set(null);
    this._pageHasMore.set(false);
    this._pageNextCursor.set(null);
    this.error.set(null);
  }

  // ── Paging handlers ────────────────────────────────────────────────────────

  async nextPage(): Promise<void> {
    if (this.loading() || !this.hasNext()) return;
    const cursor = this.cursorAfterCurrentPage();
    if (!cursor) return;
    const target = this.pageIndex() + 1;
    this.cursorForPage[target] = cursor;
    await this.fetchPage(target, cursor);
  }

  async prevPage(): Promise<void> {
    if (this.loading() || !this.hasPrev()) return;
    const target = this.pageIndex() - 1;
    const cursor = this.cursorForPage[target] ?? null;
    // Back to the live page: the websocket already holds those rows — scoped
    // the same way — so going there is a state change rather than a fetch.
    if (target === 0) {
      this.pageIndex.set(0);
      this._pageRows.set([]);
      return;
    }
    await this.fetchPage(target, cursor);
  }

  /**
   * Where the next page starts: after a fetched page the server says so, and on
   * the live page the last row on screen is the boundary.
   */
  private cursorAfterCurrentPage(): RequestCursor | null {
    if (!this.onLivePage()) return this._pageNextCursor();
    const rows = this._liveRequests();
    const last = rows[rows.length - 1];
    if (!last?.request_id) return null;
    const ts = last.enqueue_ts ?? last.timestamp;
    return ts ? { ts, request_id: last.request_id } : null;
  }

  private async fetchPage(index: number, cursor: RequestCursor | null): Promise<void> {
    const range = this.range;
    if (!range) return;

    this.loading.set(true);
    this.error.set(null);
    try {
      const page: LatestRequestsPage = await this.statisticsService.getLatestRequests(
        range.startIso,
        range.endIso,
        PAGE_SIZE,
        { userId: this._filterUserId(), teamId: this._filterTeamId() },
        cursor,
      );
      const rows = page.requests ?? [];
      // An empty page past the first is a dead end — the range held exactly a
      // multiple of the page size, or rows fell out of it while the operator
      // paged. Stay where we are and retire Next rather than parking them on a
      // blank page they have to click back out of.
      if (rows.length === 0 && index > 0) {
        this._pageHasMore.set(false);
        this._pageNextCursor.set(null);
        return;
      }
      this._pageRows.set(rows);
      this._pageTotal.set(typeof page.total === 'number' ? page.total : null);
      this._pageHasMore.set(page.has_more === true);
      this._pageNextCursor.set(page.next_cursor ?? null);
      this.pageIndex.set(index);
    } catch (err: unknown) {
      const e = err as { status?: number; error?: { error?: string; detail?: string } };
      const detail = e.error?.error ?? e.error?.detail ?? `HTTP ${e.status}`;
      this.error.set(`Could not load requests: ${detail}`);
    } finally {
      this.loading.set(false);
    }
  }

  // ── Ticker ─────────────────────────────────────────────────────────────────

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

  /** 'none' while the request is still queued — see `providerLabel`. */
  providerLabelOf(item: RequestItem): string {
    return providerLabel(item);
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

  /**
   * Generation rate of a request that is still streaming.
   *
   * Only while it runs: once it finishes, an average over its whole span says
   * less than the duration already on the row, and a figure that stops moving
   * next to counts that stopped moving reads as part of the record rather than
   * as a live measurement.
   */
  rateLabelOf(item: RequestItem): string | null {
    if (!item.streaming) return null;
    const rate = item.tokens_per_second;
    if (typeof rate !== 'number' || !Number.isFinite(rate) || rate <= 0) return null;
    return `${rate < 10 ? rate.toFixed(1) : Math.round(rate)} tok/s`;
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
