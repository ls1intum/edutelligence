import { Component, OnInit, inject, ChangeDetectionStrategy, signal } from '@angular/core';
import { Router } from '@angular/router';
import { Logo } from '../../shared/components/logo/logo';
import { ThemeToggle } from '../../shared/components/theme-toggle/theme-toggle';
import { ErrorMessageComponent } from '../../shared/components/error-message/error-message';
import { PublicStatsPie } from './public-stats.pie';
import { PublicStatsSplit } from './public-stats.split';
import { PublicStatsService, PublicStats as PublicStatsData } from './public-stats.service';
import {
  ChartSlice,
  formatAverage,
  formatCount,
  keyTypeSlices,
  laneSlices,
  teamSlices as buildTeamSlices,
} from './public-stats.utils';

/**
 * The public stats page — the one Logos screen readable without signing in.
 * Every number counts settled successes only; the page says so, and the
 * admin statistics page keeps the failure detail.
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

  stats = signal<PublicStatsData | null>(null);
  error = signal('');
  teamSlices = signal<ChartSlice[]>([]);
  keySlices = signal<ChartSlice[]>([]);
  laneSlices = signal<ChartSlice[]>([]);

  ngOnInit(): void {
    this.service
      .getStats()
      .then((data) => {
        this.stats.set(data);
        this.teamSlices.set(buildTeamSlices(data.requests_per_team));
        this.keySlices.set(keyTypeSlices(data));
        this.laneSlices.set(laneSlices(data));
      })
      .catch(() => this.error.set('The statistics could not be loaded. Please try again.'));
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
}
