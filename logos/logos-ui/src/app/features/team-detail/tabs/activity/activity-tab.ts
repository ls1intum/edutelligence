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
import { deriveStage, formatTimeAgo, formatTokenCount } from '../../../statistics/statistics.utils';
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

  /**
   * Load bookkeeping, numbered in the order the loads start. The pager only
   * moves while the newest unsettled load is out, and a load may only apply
   * its answer while it is still the newest: with a page still loading, a
   * click used to advance the index on the strength of the previous page's
   * answer — its `has_more` flag and next cursor both pointed at the page
   * behind — walking past the last page (issue #799).
   */
  private loadSeq = 0;
  /** Seqs of the loads still out. */
  private inFlightSeqs = new Set<number>();
  /** Highest seq still out, 0 when none. */
  private newestInFlight = signal(0);
  /** Highest seq that has settled, however its answer was fated. */
  private settledSeq = signal(0);

  private timer: ReturnType<typeof setInterval> | null = null;

  readonly selectedDaysValue = computed(() => String(this.days()));

  /**
   * The hint the export control carries (issue #667): a team whose keys all
   * stay on billing logging never had request or response content stored, so
   * the download holds metadata without content — say so before the click
   * instead of letting the empty columns speak for themselves.
   */
  readonly fullLoggingHint = computed<string | null>(() => {
    const activity = this.activity();
    if (!activity || activity.full_logging_enabled) return null;
    return 'Full logging is not activated for this team — the export will not contain request or response content.';
  });

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
   * A load the pager must wait for is still out. The pager waits only on the
   * newest unsettled load: an older one's answer will be dropped, so it
   * cannot push the page anywhere — letting a slow stale request hold the
   * buttons shut would just stall the pager after the shown page is ready
   * (issue #799).
   */
  readonly pageLoadInFlight = computed(() => this.newestInFlight() > this.settledSeq());

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
   * Download the team's request traces as the picked file format: every
   * request of the selected window, and for the consented (FULL-logging)
   * ones the stored request and response content with it. The server answers
   * the JSON envelope; the CSV is cut from it here, the same way the import
   * credentials file is cut from the upload result.
   */
  async exportTraces(): Promise<void> {
    if (!this.teamId || this.exporting()) return;
    // The download is named after the team the export was started for, not the
    // team the tab shows when the response lands: the tab may switch teams
    // mid-flight, and relabeling one team's data under another's id would be
    // worse than a stale number.
    const teamId = this.teamId;
    this.exporting.set(true);
    this.exportError.set(null);
    try {
      const payload = await this.activityService.getTraceExport(
        teamId,
        this.days(),
        this.filterUserId(),
      );
      const format = this.exportFormat();
      this.downloadFile(
        `logos-traces-team-${teamId}-${payload.days}d.${format}`,
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
    return formatTokenCount(value);
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
    this.inFlightSeqs.add(seq);
    this.newestInFlight.set(seq);
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
      this.inFlightSeqs.delete(seq);
      this.settledSeq.update((s) => Math.max(s, seq));
      const stillOut = [...this.inFlightSeqs];
      this.newestInFlight.set(stillOut.length > 0 ? Math.max(...stillOut) : 0);
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
  'provider_type',
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
