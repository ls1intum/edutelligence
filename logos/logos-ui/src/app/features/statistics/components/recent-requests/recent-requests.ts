import {
  Component,
  Input,
  OnInit,
  OnChanges,
  OnDestroy,
  inject,
  signal,
  computed,
  ChangeDetectionStrategy,
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { StatisticsService } from '../../services/statistics.service';
import {
  RequestItem,
  PaginatedRequestItem,
  PaginatedRequestResponse,
} from '../../statistics.models';
import {
  deriveStage,
  getRequestBorderColor,
  formatTimeAgo,
  formatElapsed,
  mergeWithLive,
  RequestStage,
} from '../../statistics.utils';
import { StatsSkeletonComponent } from '../skeletons/skeletons';

const PER_PAGE = 5;

@Component({
  selector: 'app-stats-recent-requests',
  standalone: true,
  imports: [CommonModule, StatsSkeletonComponent],
  templateUrl: './recent-requests.html',
  changeDetection: ChangeDetectionStrategy.Eager,
  styleUrl: './recent-requests.scss',
})
export class RecentRequests implements OnInit, OnChanges, OnDestroy {
  @Input() liveRequests: RequestItem[] = [];
  @Input() nowMs = Date.now();

  private statsService = inject(StatisticsService);

  readonly PER_PAGE = PER_PAGE;

  page = signal(1);
  pageData = signal<PaginatedRequestResponse | null>(null);
  loading = signal(false);
  fetchError = signal<string | null>(null);

  /** Shared ticker — ms since epoch, updated by setInterval. */
  now = signal(Date.now());

  private intervalId: ReturnType<typeof setInterval> | null = null;
  private prevLiveCount = 0;

  displayItems = computed((): PaginatedRequestItem[] => {
    const data = this.pageData();
    if (!data) return [];
    if (this.page() === 1) {
      return mergeWithLive(this.liveRequests, data.requests, PER_PAGE);
    }
    return data.requests;
  });

  private hasLive = computed(() =>
    this.displayItems().some((it) => deriveStage(it) !== 'complete'),
  );

  ngOnInit(): void {
    this.load(1);
    this.scheduleTicker();
  }

  ngOnChanges(): void {
    if (this.page() === 1 && this.liveRequests.length !== this.prevLiveCount) {
      this.prevLiveCount = this.liveRequests.length;
      this.silentRefresh();
    }
    // Re-schedule ticker whenever inputs change so cadence stays correct.
    this.scheduleTicker();
  }

  ngOnDestroy(): void {
    this.clearTicker();
  }

  async load(targetPage: number): Promise<void> {
    this.loading.set(true);
    this.fetchError.set(null);
    try {
      const data = await this.statsService.getPaginatedRequests(targetPage, PER_PAGE);
      this.pageData.set(data);
      this.page.set(targetPage);
      this.scheduleTicker();
    } catch (err: unknown) {
      const e = err as { message?: string };
      this.fetchError.set(e?.message ?? 'Failed to load requests');
    } finally {
      this.loading.set(false);
    }
  }

  private async silentRefresh(): Promise<void> {
    try {
      const data = await this.statsService.getPaginatedRequests(1, PER_PAGE);
      if (this.page() === 1) {
        this.pageData.set(data);
        this.scheduleTicker();
      }
    } catch {
      /* silent — don't surface background refresh failures */
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

  totalPages(): number {
    return this.pageData()?.total_pages ?? 1;
  }

  // ── Template helpers ─────────────────────────────────────────────────────

  stageOf(item: PaginatedRequestItem): RequestStage {
    return deriveStage(item);
  }

  borderColorOf(item: PaginatedRequestItem): string {
    return getRequestBorderColor(deriveStage(item), item.status);
  }

  bgTintOf(item: PaginatedRequestItem): string {
    const color = getRequestBorderColor(deriveStage(item), item.status);
    // wrap with low-opacity version for tinted background
    return color.replace('rgb(var(', 'rgb(var(').replace('))', ') / 0.07)');
  }

  timeAgoOf(item: PaginatedRequestItem): string {
    return formatTimeAgo(item.enqueue_ts ?? item.timestamp, this.now());
  }

  totalTimeLabelOf(item: PaginatedRequestItem): string {
    const stage = deriveStage(item);
    if (stage === 'complete' && item.total_seconds != null) {
      return `${item.total_seconds.toFixed(2)}s`;
    }
    if (item.enqueue_ts) {
      return formatElapsed((this.now() - new Date(item.enqueue_ts).getTime()) / 1000);
    }
    return '...';
  }

  elapsedOf(item: PaginatedRequestItem): string {
    if (!item.scheduled_ts) return '0.0s';
    return formatElapsed((this.now() - new Date(item.scheduled_ts).getTime()) / 1000);
  }

  errorSnippet(msg: string | null): string {
    if (!msg) return '';
    return msg.length > 60 ? msg.slice(0, 60) + '...' : msg;
  }

  trackById(_: number, item: PaginatedRequestItem): string {
    return item.request_id;
  }
}
