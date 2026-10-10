import { Component, Input, ChangeDetectionStrategy, signal } from '@angular/core';
import { TrendPoint, formatCompact, formatCount as formatCountUtil } from './public-stats.utils';

/** One drawn bar of the growth chart. */
interface TrendBar {
  point: TrendPoint;
  /** Bar height as a percentage of the tallest month. */
  percent: number;
  /** Whether the month name is printed under the bar. */
  labelled: boolean;
  marked: boolean;
}

/**
 * Monthly bars for one metric of the growth chart. Bars are flex items, so
 * the chart fills any width and its text keeps its size on a phone. An
 * optional marker names the month something started (e.g. the Logos Agent),
 * so the curve reads against a concrete event.
 */
@Component({
  selector: 'app-public-stats-trend',
  standalone: true,
  templateUrl: './public-stats.trend.html',
  changeDetection: ChangeDetectionStrategy.Eager,
  styleUrl: './public-stats.trend.scss',
})
export class PublicStatsTrend {
  @Input() points: TrendPoint[] = [];
  /** Key of the month the marker sits on; null for no marker. */
  @Input() markerKey: string | null = null;
  @Input() markerLabel = '';
  /** Accessible name for the chart. */
  @Input() label = 'Monthly trend';

  hovered = signal<string | null>(null);

  // Getters for the same reason as the split bar: inputs are plain fields.
  get max(): number {
    return this.points.reduce((m, p) => Math.max(m, p.value), 0);
  }

  get bars(): TrendBar[] {
    const n = this.points.length;
    const max = this.max;
    // Print at most about six month names; always the last one.
    const every = Math.max(1, Math.ceil(n / 6));
    return this.points.map((point, i) => ({
      point,
      percent: max === 0 ? 0 : (point.value / max) * 100,
      labelled: (n - 1 - i) % every === 0,
      marked: point.key === this.markerKey,
    }));
  }

  get readout(): string {
    const key = this.hovered() ?? this.points[this.points.length - 1]?.key;
    const point = this.points.find((p) => p.key === key);
    return point ? `${point.label}: ${formatCountUtil(point.value)}` : '';
  }

  formatCompact(value: number): string {
    return formatCompact(value);
  }

  formatCount(value: number): string {
    return formatCountUtil(value);
  }
}
