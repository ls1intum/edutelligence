import { Component, OnInit, inject, signal } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { firstValueFrom } from 'rxjs';
import { ThemeToggle } from '../../shared/components/theme-toggle/theme-toggle';
import { Logo } from '../../shared/components/logo/logo';

/** One day of the response's time series, as the API hands it out. */
interface PublicStatsDay {
  timestamp: number;
  requests: number;
}

interface PublicStatsModel {
  modelId: number | null;
  modelName: string;
  requestCount: number;
}

interface PublicStatsResponse {
  range: { start: string; end: string };
  totals: { requests: number; totalTokens: number };
  models: PublicStatsModel[];
  timeSeries: PublicStatsDay[];
}

const DAY_MS = 86_400_000;

/**
 * The public statistics page — the one Logos route that answers without a
 * session. It shows the successful requests of the teams that opted in
 * (GET /api/stats, permitted in the application server's security chain), so
 * there is nothing to hide behind the auth guard and nothing to log in for.
 */
@Component({
  selector: 'app-public-stats',
  standalone: true,
  imports: [ThemeToggle, Logo],
  templateUrl: './public-stats.html',
  styleUrl: './public-stats.scss',
})
export class PublicStats implements OnInit {
  private http = inject(HttpClient);

  readonly RANGES = [
    { days: 7, label: '7 days' },
    { days: 30, label: '30 days' },
    { days: 90, label: '90 days' },
  ];
  rangeDays = signal(30);

  loading = signal(true);
  loadError = signal('');
  data = signal<PublicStatsResponse | null>(null);

  ngOnInit(): void {
    void this.load();
  }

  setRange(days: number): void {
    if (days === this.rangeDays() || this.loading()) return;
    this.rangeDays.set(days);
    void this.load();
  }

  private async load(): Promise<void> {
    this.loading.set(true);
    this.loadError.set('');
    try {
      // Both bounds come from one clock reading: the window is then exactly
      // the selected number of days, so a request can never drift past the
      // platform's 90-day cap between the two ends being calculated —
      // neither across a second boundary nor against a server clock that
      // runs ahead of the browser's.
      const end = Date.now();
      const start = end - this.rangeDays() * DAY_MS;
      const query = `start_date=${new Date(start).toISOString()}&end_date=${new Date(end).toISOString()}`;
      this.data.set(
        await firstValueFrom(this.http.get<PublicStatsResponse>(`/api/stats?${query}`)),
      );
    } catch {
      this.data.set(null);
      this.loadError.set('The public statistics could not be loaded, please try again.');
    } finally {
      this.loading.set(false);
    }
  }

  get models(): PublicStatsModel[] {
    return this.data()?.models ?? [];
  }

  /**
   * Live rows are tracked by model id; a deleted model has none, and its
   * name must not collide with a same-named replacement that has one.
   */
  modelTrackKey(model: PublicStatsModel): string {
    return model.modelId !== null ? `id:${model.modelId}` : `deleted:${model.modelName}`;
  }

  get timeSeries(): PublicStatsDay[] {
    return this.data()?.timeSeries ?? [];
  }

  /** The busiest day: the chart's scale, so the bars compare with each other. */
  get maxDailyRequests(): number {
    return this.timeSeries.reduce((max, d) => Math.max(max, d.requests), 0);
  }

  get busiestModelCount(): number {
    return this.models.reduce((max, m) => Math.max(max, m.requestCount), 0);
  }

  get hasTraffic(): boolean {
    return (this.data()?.totals.requests ?? 0) > 0;
  }

  rangeLabel(): string {
    const range = this.data()?.range;
    if (!range) return '';
    return `${this.formatDay(range.start)} – ${this.formatDay(range.end)}`;
  }

  formatCount(value: number | null | undefined): string {
    return new Intl.NumberFormat('en-US').format(value ?? 0);
  }

  formatDay(isoOrEpoch: string | number): string {
    const date = typeof isoOrEpoch === 'number' ? new Date(isoOrEpoch) : new Date(isoOrEpoch);
    return new Intl.DateTimeFormat('en-US', { month: 'short', day: 'numeric', timeZone: 'UTC' }).format(date);
  }

  /** The chart's bar height for a day, scaled to the busiest day. */
  barHeight(requests: number): number {
    const max = this.maxDailyRequests;
    if (max <= 0) return 0;
    // A floor of 2% keeps a quiet-but-nonzero day visible rather than vanished.
    return Math.max((requests / max) * 100, requests > 0 ? 2 : 0);
  }

  /** The model list's bar width for one model, scaled to the busiest model. */
  modelShare(requestCount: number): number {
    const max = this.busiestModelCount;
    if (max <= 0) return 0;
    return Math.max((requestCount / max) * 100, requestCount > 0 ? 2 : 0);
  }
}
