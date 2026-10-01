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

import { HttpResponse } from '@angular/common/http';
import { AppSelectOption, SelectComponent } from '../../../../shared/components/select/select';
import { RequestItem } from '../../../statistics/statistics.models';
import { deriveStage, formatTimeAgo, formatTokenCount } from '../../../statistics/statistics.utils';
import { TeamActivityService } from './activity-tab.service';
import { ExportCursor, RequestCursor, TeamActivityPayload } from './activity-tab.models';
import { MostAskedQuestions } from './most-asked-questions';

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
 * behind both.
 *
 * Sits next to Cloud Usage, which answers the same period in money: that tab
 * is what the cloud providers billed, this one is what the platform did. A
 * local model costs nothing and still consumes the cluster, so neither view
 * substitutes for the other.
 */
@Component({
  selector: 'app-activity-tab',
  standalone: true,
  imports: [CommonModule, SelectComponent, MostAskedQuestions],
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

  // ── Trace export ─────────────────────────────────────────────

  readonly exportFormat = signal<'json' | 'csv'>('json');
  readonly exporting = signal(false);
  readonly exportError = signal<string | null>(null);
  /**
   * What the last download covered: the server caps one export, so a file
   * that holds fewer requests than the window did must say so — a capped
   * download that reads as a complete one is a data-loss story waiting to
   * happen.
   */
  readonly exportNotice = signal<string | null>(null);
  /**
   * Where the last download's slice ended: a capped export hands the button
   * over to the next, older slice instead of leaving its rows unreachable.
   */
  readonly exportCursor = signal<ExportCursor | null>(null);

  readonly exportFormatOptions: AppSelectOption[] = [
    { value: 'json', label: 'JSON' },
    { value: 'csv', label: 'CSV' },
  ];

  readonly selectedExportFormatValue = computed(() => this.exportFormat());

  /**
   * The export button doubles as the continuation once a slice was capped,
   * so its label says which of the two it is doing.
   */
  readonly exportButtonTitle = computed(() =>
    this.exportCursor()
      ? "Download the next, older slice of this team's requests"
      : "Download this team's requests — the full-logging ones carry their stored content",
  );
  readonly exportButtonLabel = computed(() =>
    this.exportCursor() ? 'Export the next older request traces' : 'Export request traces',
  );

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
   * behind — walking past the last page.
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
   * The hint the export control carries: a team whose keys all
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
   * ones the stored request and response content with it. Both formats are
   * cut on the application server and arrive as a file — the view only names
   * it, saves it, and says what it holds.
   *
   * A window the cap outruns is not a dead end: the first download carries
   * the newest slice and the cursor behind it, and every following click
   * carries the cursor back so the server sends the next, older slice —
   * until a file arrives uncapped, which ends the walk.
   */
  async exportTraces(): Promise<void> {
    if (!this.teamId || this.exporting()) return;
    // The download is named after the team the export was started for, not the
    // team the tab shows when the response lands: the tab may switch teams
    // mid-flight, and relabeling one team's data under another's id would be
    // worse than a stale number.
    const teamId = this.teamId;
    const days = this.days();
    const userId = this.filterUserId();
    const format = this.exportFormat();
    const cursor = this.exportCursor();
    this.exporting.set(true);
    this.exportError.set(null);
    try {
      const response = await this.activityService.getTraceExport(teamId, days, userId, format, cursor);
      this.downloadFile(response, `logos-traces-team-${teamId}-${days}d.${format}`);
      // The scope may have moved while the download was out — the change
      // already cleared the last notice and the cursor it belonged to, and a
      // late answer must not put either back for a selection that is no
      // longer on screen. The file itself still gets saved: it is a complete
      // answer for the scope it was started with.
      if (this.teamId !== teamId || this.days() !== days || this.filterUserId() !== userId) {
        this.exportNotice.set(null);
        this.exportCursor.set(null);
        return;
      }
      // The headers are set before the first byte, so they are the same facts
      // the file carries — and the only ones the view can read back.
      const total = Number(response.headers.get('X-Logos-Export-Total') ?? '0');
      const count = Number(response.headers.get('X-Logos-Export-Count') ?? '0');
      if (response.headers.get('X-Logos-Export-Truncated') !== 'true') {
        this.exportCursor.set(null);
        this.exportNotice.set(null);
        return;
      }
      const next = this.parseNextCursor(response.headers.get('X-Logos-Export-Next-Cursor') ?? '');
      this.exportCursor.set(next);
      this.exportNotice.set(
        next
          ? `The export carries the ${count.toLocaleString()} newest requests of ${total.toLocaleString()} in the selected period — press export again for the next, older slice.`
          : `The export carries the ${count.toLocaleString()} newest requests of ${total.toLocaleString()} in the selected period — narrow the period or the requester filter for the rest.`,
      );
    } catch (err: unknown) {
      // A continuation the server refuses (expired walk / malformed token) is
      // a 400. Keeping that cursor would make every following click resend the
      // same rejected token; clear it so the next press starts a fresh export.
      // Network / 5xx failures keep the cursor so a retry can resume.
      const status =
        err && typeof err === 'object' && 'status' in err
          ? Number((err as { status: unknown }).status)
          : NaN;
      if (cursor != null && status === 400) {
        this.exportCursor.set(null);
        this.exportError.set(
          'The previous export continuation expired — press export again to start a fresh download.',
        );
        this.exportNotice.set(null);
      } else {
        this.exportError.set('Could not export the traces.');
        this.exportNotice.set(null);
      }
    } finally {
      this.exporting.set(false);
    }
  }

  /**
   * The server's continuation token is opaque: the view neither parses nor
   * builds it, it only decides whether the header holds one at all. An empty
   * token means the walk cannot continue, and the notice then says so with
   * the narrowing advice instead of promising a next slice.
   */
  private parseNextCursor(token: string): ExportCursor | null {
    return token.trim() ? token : null;
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
    // A notice about the last download describes the window and filter it
    // was cut from; a new scope would leave it describing something that is
    // not on screen anymore. The export cursor belongs to the same scope — a
    // continuation started under one window must not fire under another.
    this.exportNotice.set(null);
    this.exportCursor.set(null);
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
      // the last page.
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

  private downloadFile(response: HttpResponse<Blob>, fallbackName: string): void {
    const body = response.body;
    if (!body) return;
    const url = URL.createObjectURL(body);
    const a = document.createElement('a');
    a.href = url;
    a.download = this.fileNameFrom(response, fallbackName);
    a.click();
    URL.revokeObjectURL(url);
  }

  /**
   * The file name the server picked for the download, out of the
   * Content-Disposition header — the header is the file's own name, and the
   * fallback keeps a download that lost its headers under a sane one.
   */
  private fileNameFrom(response: HttpResponse<Blob>, fallback: string): string {
    const disposition = response.headers.get('Content-Disposition') ?? '';
    const named = /filename\*?=(?:UTF-8'')?"?([^";]+)"?/i.exec(disposition);
    return named?.[1] ?? fallback;
  }
}
