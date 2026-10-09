import { Component, OnInit, inject, ChangeDetectionStrategy, computed, signal } from '@angular/core';
import { Router } from '@angular/router';
import { Logo } from '../../shared/components/logo/logo';
import { ThemeToggle } from '../../shared/components/theme-toggle/theme-toggle';
import { ErrorMessageComponent } from '../../shared/components/error-message/error-message';
import { PublicStatsPie } from './public-stats.pie';
import { PublicStatsSplit } from './public-stats.split';
import { PublicStatsTrend } from './public-stats.trend';
import {
  DEFAULT_PUBLIC_STATS_DAYS,
  PUBLIC_STATS_DAY_OPTIONS,
  PublicStatsDays,
  PublicStatsService,
  PublicStats as PublicStatsData,
  PublicUsageDistribution,
} from './public-stats.service';
import {
  ChartSlice,
  TREND_METRICS,
  TrendMetric,
  categorySlices as buildCategorySlices,
  formatAverage,
  formatCompact,
  formatCount,
  keyTypeSlices,
  laneSlices,
  laneTokenSlices as buildLaneTokenSlices,
  modelSlices as buildModelSlices,
  teamSlices as buildTeamSlices,
  trendPoints,
  windowLabel,
} from './public-stats.utils';

/** Which models the model chart lists. */
type ModelLane = 'all' | 'local' | 'cloud';

/** One row of the usage table: a figure's median and heavy-user value, formatted. */
interface UsageRow {
  key: string;
  label: string;
  median: string;
  p90: string;
}

/**
 * The public stats page — the one Logos screen readable without signing in.
 * Every number counts settled successes on opted-in teams inside the selected
 * window; the page says so, and the admin statistics page keeps the failure detail.
 */
@Component({
  selector: 'app-public-stats',
  standalone: true,
  imports: [Logo, ThemeToggle, ErrorMessageComponent, PublicStatsPie, PublicStatsSplit, PublicStatsTrend],
  templateUrl: './public-stats.html',
  changeDetection: ChangeDetectionStrategy.Eager,
  styleUrl: './public-stats.scss',
})
export class PublicStats implements OnInit {
  private service = inject(PublicStatsService);
  private router = inject(Router);

  readonly dayOptions = PUBLIC_STATS_DAY_OPTIONS;
  readonly trendMetrics = TREND_METRICS;
  readonly modelLanes: { value: ModelLane; label: string }[] = [
    { value: 'all', label: 'All' },
    { value: 'local', label: 'Local' },
    { value: 'cloud', label: 'Cloud' },
  ];

  days = signal<PublicStatsDays>(DEFAULT_PUBLIC_STATS_DAYS);
  stats = signal<PublicStatsData | null>(null);
  error = signal('');
  loading = signal(true);
  teamSlices = signal<ChartSlice[]>([]);
  keySlices = signal<ChartSlice[]>([]);
  laneSlices = signal<ChartSlice[]>([]);
  laneTokenSlices = signal<ChartSlice[]>([]);
  categorySlices = signal<ChartSlice[]>([]);
  trendMetric = signal<TrendMetric>('persons');
  modelLane = signal<ModelLane>('all');

  trend = computed(() => trendPoints(this.stats()?.monthly ?? [], this.trendMetric()));
  trendLabel = computed(
    () => `${TREND_METRICS.find((m) => m.value === this.trendMetric())?.label ?? ''} per month`
  );
  /** The month of the first Logos Agent session, where the growth chart puts its marker. */
  agentLaunchMonth = computed(() => this.stats()?.agent.first_session_day?.slice(0, 7) ?? null);
  modelSlices = computed(() => {
    const models = this.stats()?.models;
    return models ? buildModelSlices(models[this.modelLane()]) : [];
  });
  localTokenShare = computed(() => {
    const lc = this.stats()?.local_cloud_tokens;
    const total = lc ? lc.local + lc.cloud + (lc.unknown ?? 0) : 0;
    return total === 0 ? 0 : Math.round((lc!.local / total) * 100);
  });
  usageRows = computed<UsageRow[]>(() => {
    const data = this.stats();
    if (!data) return [];
    return [
      usageRow('person-requests', 'Requests per person', data.usage_per_person, 'requests', formatCount),
      usageRow('person-tokens', 'Tokens per person', data.usage_per_person, 'tokens', formatCompact),
      usageRow('person-days', 'Active days per person', data.usage_per_person, 'active_days', formatAverage),
      usageRow('team-requests', 'Requests per team', data.usage_per_team, 'requests', formatCount),
      usageRow('team-tokens', 'Tokens per team', data.usage_per_team, 'tokens', formatCompact),
    ];
  });

  /** Ignores out-of-order responses when the reader switches windows quickly. */
  private loadSeq = 0;

  ngOnInit(): void {
    void this.load();
  }

  selectDays(days: PublicStatsDays): void {
    if (days === this.days()) return;
    this.days.set(days);
    void this.load();
  }

  private async load(): Promise<void> {
    const seq = ++this.loadSeq;
    this.loading.set(true);
    this.error.set('');
    try {
      const data = await this.service.getStats(this.days());
      if (seq !== this.loadSeq) return;
      this.stats.set(data);
      this.teamSlices.set(buildTeamSlices(data.requests_per_team));
      this.keySlices.set(keyTypeSlices(data));
      this.laneSlices.set(laneSlices(data));
      this.laneTokenSlices.set(buildLaneTokenSlices(data));
      this.categorySlices.set(buildCategorySlices(data.categories));
    } catch {
      if (seq !== this.loadSeq) return;
      this.stats.set(null);
      this.error.set('The statistics could not be loaded. Please try again.');
    } finally {
      if (seq === this.loadSeq) this.loading.set(false);
    }
  }

  /**
   * Hiding a team flips its row out of the pie — the slice order and the
   * colors the remaining teams wear do not move, so the chart never repaints
   * while the reader curates it.
   */
  onToggleTeam(key: string): void {
    this.teamSlices.update((slices) => slices.map((s) => (s.key === key ? { ...s, hidden: !s.hidden } : s)));
  }

  signIn(): void {
    void this.router.navigate(['/']);
  }

  formatCount(value: number | null | undefined): string {
    return formatCount(value ?? 0);
  }

  formatAverage(value: number | null | undefined): string {
    return formatAverage(value ?? 0);
  }

  formatCompact(value: number | null | undefined): string {
    return formatCompact(value ?? 0);
  }

  windowCaption(): string {
    return windowLabel(this.days());
  }
}

function usageRow(
  key: string,
  label: string,
  distribution: PublicUsageDistribution,
  figure: 'requests' | 'tokens' | 'active_days',
  format: (value: number) => string
): UsageRow {
  const values = distribution[figure];
  return {
    key,
    label,
    median: values ? format(Math.round(values.median * 10) / 10) : '–',
    p90: values ? format(Math.round(values.p90 * 10) / 10) : '–',
  };
}
