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
import { AppSelectOption, SelectComponent } from '../../../../shared/components/select/select';
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
  RequestStage,
} from '../../statistics.utils';

/**
 * Rows per page. Must stay in sync with
 * `RequestLogService.LATEST_REQUESTS_PAGE_SIZE`, which is what the websocket
 * pushes — otherwise page 1 (the live rows) and every fetched page would be
 * sized differently and the "1-10 of n" count would skip or repeat numbers.
 */
const PAGE_SIZE = 10;

/** One entry of the requester/team filter dropdowns. */
export interface FeedFilterOption {
  id: number;
  label: string;
}

@Component({
  selector: 'app-stats-recent-requests',
  standalone: true,
  imports: [CommonModule, SelectComponent, StatsSkeletonComponent],
  templateUrl: './recent-requests.html',
  changeDetection: ChangeDetectionStrategy.Eager,
  styleUrl: './recent-requests.scss',
})
export class RecentRequests implements OnChanges, OnDestroy {
  private statisticsService = inject(StatisticsService);

  /** Live rows pushed by the stats WS (newest page, unfiltered). */
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

  /** Requesters to offer in the filter (all platform users). */
  @Input() users: FeedFilterOption[] = [];

  /** Teams to offer in the filter. */
  @Input() teams: FeedFilterOption[] = [];

  /** Shared ticker: ms since epoch, updated by setInterval. */
  now = signal(Date.now());

  private intervalId: ReturnType<typeof setInterval> | null = null;

  // Input mirror signals so the computed()s below actually react: a plain
  // @Input() is not a tracked producer, so reading it inside computed() would
  // cache the very first value (an empty list) forever.
  private readonly _liveRequests = signal<RequestItem[]>([]);
  private readonly _totalInRange = signal(0);
  private readonly _users = signal<FeedFilterOption[]>([]);
  private readonly _teams = signal<FeedFilterOption[]>([]);

  // ── Filter ─────────────────────────────────────────────────────────────────

  readonly filterUserId = signal<number | null>(null);
  readonly filterTeamId = signal<number | null>(null);

  readonly filterActive = computed(
    () => this.filterUserId() !== null || this.filterTeamId() !== null,
  );

  // ── Paging ─────────────────────────────────────────────────────────────────

  /** 0-based. Page 0 unfiltered is the live feed; everything else is fetched. */
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

  /** True while page 1 shows what the websocket pushes rather than a fetch. */
  readonly onLivePage = computed(() => this.pageIndex() === 0 && !this.filterActive());

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

  // ── Filter dropdown options ────────────────────────────────────────────────

  readonly userOptions = computed<AppSelectOption[]>(() => [
    { value: '', label: 'All requesters' },
    ...this._users().map((u) => ({ value: String(u.id), label: u.label })),
  ]);

  readonly teamOptions = computed<AppSelectOption[]>(() => [
    { value: '', label: 'All teams' },
    ...this._teams().map((t) => ({ value: String(t.id), label: t.label })),
  ]);

  readonly selectedUserValue = computed(() => {
    const id = this.filterUserId();
    return id === null ? '' : String(id);
  });

  readonly selectedTeamValue = computed(() => {
    const id = this.filterTeamId();
    return id === null ? '' : String(id);
  });

  private hasLive = computed(() =>
    this.displayItems().some((it) => deriveStage(it) !== 'complete'),
  );

  ngOnChanges(changes: SimpleChanges): void {
    if (changes['liveRequests']) this._liveRequests.set(this.liveRequests ?? []);
    if (changes['totalInRange']) this._totalInRange.set(this.totalInRange ?? 0);
    if (changes['users']) this._users.set(this.users ?? []);
    if (changes['teams']) this._teams.set(this.teams ?? []);
    // A new range invalidates every page cut out of the previous one.
    if (changes['range'] && !changes['range'].firstChange) {
      this.resetToFirstPage();
      if (this.filterActive()) void this.fetchPage(0, null);
    }
    // Re-schedule ticker whenever inputs change so cadence stays correct.
    this.scheduleTicker();
  }

  ngOnDestroy(): void {
    this.clearTicker();
  }

  // ── Filter handlers ────────────────────────────────────────────────────────

  setUserFilter(value: string | null): void {
    const id = value ? Number(value) : null;
    if (id === this.filterUserId()) return;
    this.filterUserId.set(Number.isFinite(id as number) ? id : null);
    this.onFilterChanged();
  }

  setTeamFilter(value: string | null): void {
    const id = value ? Number(value) : null;
    if (id === this.filterTeamId()) return;
    this.filterTeamId.set(Number.isFinite(id as number) ? id : null);
    this.onFilterChanged();
  }

  clearFilter(): void {
    if (!this.filterActive()) return;
    this.filterUserId.set(null);
    this.filterTeamId.set(null);
    this.onFilterChanged();
  }

  /**
   * A narrowed feed is served entirely over REST rather than taught to the
   * websocket: the push runs every 2 s for every open session, and a filtered
   * view is a question the operator asks, not a tail they watch.
   */
  private onFilterChanged(): void {
    this.resetToFirstPage();
    if (this.filterActive()) void this.fetchPage(0, null);
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
    // Back to the live page: the websocket already holds those rows, so going
    // there is a state change rather than a fetch.
    if (target === 0 && !this.filterActive()) {
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
        { userId: this.filterUserId(), teamId: this.filterTeamId() },
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
