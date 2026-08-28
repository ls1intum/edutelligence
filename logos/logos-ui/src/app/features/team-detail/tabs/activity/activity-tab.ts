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
import { RequestCursor, TeamActivityPayload, TraceExport, TraceExportItem } from './activity-tab.models';

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

  // ── Trace export (issue #667) ────────────────────────────────────────────

  readonly exportFormat = signal<'json' | 'csv'>('json');
  readonly exporting = signal(false);
  readonly exportError = signal<string | null>(null);

  readonly exportFormatOptions: AppSelectOption[] = [
    { value: 'json', label: 'JSON' },
    { value: 'csv', label: 'CSV' },
  ];

  readonly selectedExportFormatValue = computed(() => this.exportFormat());

  /**
   * Cursor of each page already visited. Page 0 is always null (start at the
   * newest); going back is a pop rather than a reverse query, because a keyset
   * cursor only points forwards.
   */
  private cursorForPage: (RequestCursor | null)[] = [null];
  readonly pageIndex = signal(0);

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

  setExportFormat(value: string | null): void {
    if (value === 'json' || value === 'csv') this.exportFormat.set(value);
  }

  /**
   * Download the team's consent-based traces — the FULL-logging requests with
   * their stored content — as the picked file format. The server answers the
   * JSON envelope; the CSV is cut from it here, the same way the import
   * credentials file is cut from the upload result.
   */
  async exportTraces(): Promise<void> {
    if (!this.teamId || this.exporting()) return;
    this.exporting.set(true);
    this.exportError.set(null);
    try {
      const payload = await this.activityService.getTraceExport(
        this.teamId,
        this.days(),
        this.filterUserId(),
      );
      const format = this.exportFormat();
      this.downloadFile(
        `logos-traces-team-${this.teamId}-${payload.days}d.${format}`,
        format === 'csv' ? tracesToCsv(payload) : JSON.stringify(payload, null, 2),
        format === 'csv' ? 'text/csv' : 'application/json',
      );
    } catch {
      this.exportError.set('Could not export the traces.');
    } finally {
      this.exporting.set(false);
    }
  }

  async nextPage(): Promise<void> {
    const cursor = this.activity()?.requests_next_cursor ?? null;
    if (!cursor || !this.hasNext()) return;
    const target = this.pageIndex() + 1;
    this.cursorForPage[target] = cursor;
    this.pageIndex.set(target);
    await this.load();
  }

  async prevPage(): Promise<void> {
    if (!this.hasPrev()) return;
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
    try {
      this.activity.set(
        await this.activityService.getActivity(this.teamId, this.days(), {
          userId: this.filterUserId(),
          cursor: this.cursorForPage[this.pageIndex()] ?? null,
        }),
      );
      this.error.set(null);
    } catch {
      // Keep whatever is on screen: this runs on a timer, and blanking the tab
      // over one failed poll would make a brief network blip look like an
      // outage.
      this.error.set('Could not refresh activity.');
    } finally {
      this.loading.set(false);
    }
  }

  private downloadFile(filename: string, content: string, mimeType: string): void {
    const blob = new Blob([content], { type: mimeType });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    a.click();
    URL.revokeObjectURL(url);
  }
}

// ── Trace export helpers (issue #667) ────────────────────────────────────────

/** Column order of the CSV export; the JSON envelope is the reference. */
export const TRACE_CSV_COLUMNS: (keyof TraceExportItem)[] = [
  'request_id',
  'timestamp_request',
  'timestamp_forwarding',
  'timestamp_response',
  'time_at_first_token',
  'privacy_level',
  'model_name',
  'provider_name',
  'provider_type',
  'policy_id',
  'environment',
  'api_key_id',
  'api_key_name',
  'username',
  'full_name',
  'team_name',
  'client_ip',
  'status',
  'error_message',
  'priority',
  'initial_priority',
  'priority_when_scheduled',
  'queue_depth_at_enqueue',
  'queue_depth_at_schedule',
  'queue_depth_at_arrival',
  'timeout_s',
  'utilization_at_arrival',
  'queue_wait_ms',
  'was_cold_start',
  'load_duration_ms',
  'available_vram_mb',
  'azure_rate_remaining_requests',
  'azure_rate_remaining_tokens',
  'prompt_tokens',
  'completion_tokens',
  'total_tokens',
  'cost_microcents',
  'classification_statistics',
  'input_payload',
  'headers',
  'response_payload',
];

/**
 * The CSV version of a trace export. Structured fields go out as compact
 * JSON so a trace stays one row; quoting follows the same rules as the import
 * credentials file — escape what breaks a table, because a payload is one
 * comma away from breaking it.
 */
export function tracesToCsv(payload: TraceExport): string {
  const rows = payload.traces.map((trace) =>
    TRACE_CSV_COLUMNS.map((column) => traceCsvCell(trace[column])).join(','),
  );
  return [TRACE_CSV_COLUMNS.join(','), ...rows].join('\n');
}

export function traceCsvCell(value: unknown): string {
  const text =
    value === null || value === undefined
      ? ''
      : typeof value === 'string'
        ? value
        : JSON.stringify(value);
  return /[",\n\r]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
}
