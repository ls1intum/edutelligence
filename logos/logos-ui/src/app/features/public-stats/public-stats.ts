import { Component, OnInit, inject, ChangeDetectionStrategy, signal } from '@angular/core';
import { Router } from '@angular/router';
import { Logo } from '../../shared/components/logo/logo';
import { ThemeToggle } from '../../shared/components/theme-toggle/theme-toggle';
import { ErrorMessageComponent } from '../../shared/components/error-message/error-message';
import { PublicStatsPie } from './public-stats.pie';
import { PublicStatsSplit } from './public-stats.split';
import {
  DEFAULT_PUBLIC_STATS_DAYS,
  PUBLIC_STATS_DAY_OPTIONS,
  PublicStatsDays,
  PublicStatsService,
  PublicStats as PublicStatsData,
} from './public-stats.service';
import {
  ChartSlice,
  formatAverage,
  formatCount,
  keyTypeSlices,
  laneSlices,
  teamSlices as buildTeamSlices,
  windowLabel,
} from './public-stats.utils';

/**
 * The public stats page — the one Logos screen readable without signing in.
 * Every number counts settled successes on opted-in teams inside the selected
 * window; the page says so, and the admin statistics page keeps the failure detail.
 */
@Component({
  selector: 'app-public-stats',
  standalone: true,
  imports: [Logo, ThemeToggle, ErrorMessageComponent, PublicStatsPie, PublicStatsSplit],
  templateUrl: './public-stats.html',
  changeDetection: ChangeDetectionStrategy.Eager,
  styleUrl: './public-stats.scss',
})
export class PublicStats implements OnInit {
  private service = inject(PublicStatsService);
  private router = inject(Router);

  readonly dayOptions = PUBLIC_STATS_DAY_OPTIONS;

  days = signal<PublicStatsDays>(DEFAULT_PUBLIC_STATS_DAYS);
  stats = signal<PublicStatsData | null>(null);
  error = signal('');
  loading = signal(true);
  teamSlices = signal<ChartSlice[]>([]);
  keySlices = signal<ChartSlice[]>([]);
  laneSlices = signal<ChartSlice[]>([]);

  ngOnInit(): void {
    void this.load();
  }

  selectDays(days: PublicStatsDays): void {
    if (days === this.days()) return;
    this.days.set(days);
    void this.load();
  }

  private async load(): Promise<void> {
    this.loading.set(true);
    this.error.set('');
    try {
      const data = await this.service.getStats(this.days());
      this.stats.set(data);
      this.teamSlices.set(buildTeamSlices(data.requests_per_team));
      this.keySlices.set(keyTypeSlices(data));
      this.laneSlices.set(laneSlices(data));
    } catch {
      this.stats.set(null);
      this.error.set('The statistics could not be loaded. Please try again.');
    } finally {
      this.loading.set(false);
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

  windowCaption(): string {
    return windowLabel(this.days());
  }
}
