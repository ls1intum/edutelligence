import { ChangeDetectionStrategy, Component, effect, inject, input, signal } from '@angular/core';
import { DataTableComponent } from '../../../shared/components/data-table/data-table';
import { StatisticsService } from '../../statistics/services/statistics.service';
import { CloudLatencyRow, CloudLatencyScope } from '../../statistics/services/cloud-latency.models';

/**
 * Format a delay in milliseconds for a table cell: below a second in whole
 * milliseconds, from a second on in seconds with one decimal, and an em dash
 * when no request carried the timestamps the figure needs.
 */
export function formatDelayMs(ms: number | null | undefined): string {
  if (ms === null || ms === undefined || !Number.isFinite(ms)) return '—';
  if (ms < 1000) return `${Math.round(ms)} ms`;
  return `${(ms / 1000).toFixed(1)} s`;
}

/**
 * Delay percentiles of finished cloud requests per model and provider: how
 * long a request waited inside Logos before the provider was called, how long
 * the provider took, and the time to the first token.
 *
 * Fetched on its own call whenever the range or the page scope changes, not
 * pushed with the other aggregates: percentiles read single requests, which
 * is too much work for the push cadence.
 */
@Component({
  selector: 'app-stats-cloud-latency-panel',
  standalone: true,
  imports: [DataTableComponent],
  templateUrl: './cloud-latency-panel.html',
  changeDetection: ChangeDetectionStrategy.Eager,
  styleUrl: './cloud-latency-panel.scss',
})
export class CloudLatencyPanel {
  private readonly statisticsService = inject(StatisticsService);

  /** Inclusive start of the range, ISO 8601. */
  readonly start = input.required<string>();
  /** Inclusive end of the range, ISO 8601. */
  readonly end = input.required<string>();
  readonly scope = input<CloudLatencyScope>({
    teamId: null,
    userId: null,
    providerId: null,
    apiKeyId: null,
    modelIds: [],
  });
  /**
   * Bumped by the host's Refresh. A calendar range read again within the same
   * period has the same start and end, so this is what reloads the table then.
   */
  readonly refresh = input(0);

  readonly rows = signal<CloudLatencyRow[]>([]);
  readonly loading = signal(true);
  readonly failed = signal(false);

  readonly columns = [
    'MODEL',
    'PROVIDER',
    'REQUESTS',
    'LOGOS WAIT P50',
    'LOGOS WAIT P95',
    'PROVIDER P50',
    'PROVIDER P95',
    'TTFT P50',
    'TTFT P95',
  ];
  readonly gridCols = '200fr 160fr 90fr 110fr 110fr 110fr 110fr 100fr 100fr';
  readonly formatDelay = formatDelayMs;

  // Every load bumps this; a response for an older range or scope must not
  // replace the rows of the current one.
  private generation = 0;

  constructor() {
    effect(() => {
      const start = this.start();
      const end = this.end();
      const scope = this.scope();
      this.refresh();
      void this.load(start, end, scope);
    });
  }

  private async load(start: string, end: string, scope: CloudLatencyScope): Promise<void> {
    const generation = ++this.generation;
    this.loading.set(true);
    this.failed.set(false);
    try {
      const stats = await this.statisticsService.getCloudLatencyStats(start, end, scope);
      if (generation !== this.generation) return;
      this.rows.set(stats.rows ?? []);
    } catch {
      if (generation !== this.generation) return;
      this.rows.set([]);
      this.failed.set(true);
    } finally {
      if (generation === this.generation) this.loading.set(false);
    }
  }
}
