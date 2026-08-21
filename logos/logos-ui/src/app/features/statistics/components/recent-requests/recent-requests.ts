import {
  Component,
  Input,
  OnChanges,
  OnDestroy,
  signal,
  computed,
  SimpleChanges,
  ChangeDetectionStrategy,
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { formatUsd } from '../../../../shared/utils/currency';
import { RequestItem } from '../../statistics.models';
import {
  deriveStage,
  getRequestBorderColor,
  formatTimeAgo,
  formatElapsed,
  RequestStage,
} from '../../statistics.utils';

const MAX_ROWS = 10;

@Component({
  selector: 'app-stats-recent-requests',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './recent-requests.html',
  changeDetection: ChangeDetectionStrategy.Eager,
  styleUrl: './recent-requests.scss',
})
export class RecentRequests implements OnChanges, OnDestroy {
  /** Live rows pushed by the stats WS (already scoped to the selected time range). */
  @Input() liveRequests: RequestItem[] = [];

  /** Shared ticker: ms since epoch, updated by setInterval. */
  now = signal(Date.now());

  private intervalId: ReturnType<typeof setInterval> | null = null;

  // Input mirror signal so the computed()s below actually react: a plain
  // @Input() is not a tracked producer, so reading it inside computed() would
  // cache the very first value (an empty list) forever.
  private readonly _liveRequests = signal<RequestItem[]>([]);

  displayItems = computed(() => this._liveRequests().slice(0, MAX_ROWS));

  private hasLive = computed(() =>
    this.displayItems().some((it) => deriveStage(it) !== 'complete'),
  );

  ngOnChanges(changes: SimpleChanges): void {
    if (changes['liveRequests']) this._liveRequests.set(this.liveRequests ?? []);
    // Re-schedule ticker whenever inputs change so cadence stays correct.
    this.scheduleTicker();
  }

  ngOnDestroy(): void {
    this.clearTicker();
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

  trackById(_: number, item: RequestItem): string {
    return item.request_id;
  }
}
