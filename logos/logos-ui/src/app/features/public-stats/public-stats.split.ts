import { Component, Input, ChangeDetectionStrategy, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { ChartSlice, formatCount as formatCountUtil } from './public-stats.utils';

/**
 * One split of the platform's successful requests — member vs. application
 * keys, local vs. cloud. A segmented bar: width is the share, the legend row
 * carries the label, the count and the percent, so nothing rides on color
 * alone.
 */
@Component({
  selector: 'app-public-stats-split',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './public-stats.split.html',
  changeDetection: ChangeDetectionStrategy.Eager,
  styleUrl: './public-stats.split.scss',
})
export class PublicStatsSplit {
  @Input() segments: ChartSlice[] = [];
  /** Accessible name for the bar; the panel heading alone is not associated with it. */
  @Input() label = 'Proportional bar';

  hovered = signal<string | null>(null);

  // Getters, not computeds: the segments arrive as a plain @Input (see the
  // pie's note), so a computed would pin the first bar forever.
  get total(): number {
    return this.segments.reduce((sum, s) => sum + s.value, 0);
  }

  get nonZero(): ChartSlice[] {
    return this.segments.filter((s) => s.value > 0);
  }

  percentOf(segment: ChartSlice): number {
    return this.total() === 0 ? 0 : Math.round((segment.value / this.total()) * 100);
  }

  isHighlighted(key: string): boolean {
    return this.hovered() === key;
  }

  trackByKey(_index: number, segment: ChartSlice): string {
    return segment.key;
  }

  formatCount(value: number): string {
    return formatCountUtil(value);
  }
}
