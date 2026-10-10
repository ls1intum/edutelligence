import { Component, EventEmitter, Input, Output, ChangeDetectionStrategy, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { ChartSlice, PieGeometry, buildPieGeometry, formatCount as formatCountUtil } from './public-stats.utils';

/**
 * The requests-per-team pie. The legend is the interaction surface: ticking
 * a team hides it from the pie (the rest re-partitions), and it can be ticked
 * back in. Identity never rides on color alone — every slice has a labelled
 * row with its count.
 */
@Component({
  selector: 'app-public-stats-pie',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './public-stats.pie.html',
  changeDetection: ChangeDetectionStrategy.Eager,
  styleUrl: './public-stats.pie.scss',
})
export class PublicStatsPie {
  @Input() slices: ChartSlice[] = [];
  @Input() title = '';
  @Output() toggleSlice = new EventEmitter<string>();

  hovered = signal<string | null>(null);

  // A getter, not a computed: the slices arrive as a plain @Input, so a
  // computed would see no signal change and keep the first pie forever.
  get geometry(): PieGeometry[] {
    return buildPieGeometry(this.slices);
  }

  get visibleTotal(): number {
    return this.slices.filter((s) => !s.hidden).reduce((sum, s) => sum + s.value, 0);
  }

  /** True when there is nothing to chart — not when the reader hid every slice. */
  hasNoData(): boolean {
    return this.slices.every((s) => s.value === 0);
  }

  /** True when slices exist but none are drawn (all hidden or zeroed out of view). */
  allHidden(): boolean {
    return !this.hasNoData() && this.visibleTotal === 0;
  }

  percentOf(slice: ChartSlice): string {
    const g = this.geometry.find((x) => x.slice.key === slice.key);
    return g ? ` (${g.percent}%)` : '';
  }

  isHighlighted(key: string): boolean {
    return this.hovered() === key;
  }

  trackByKey(_index: number, slice: ChartSlice): string {
    return slice.key;
  }

  toggle(key: string): void {
    this.toggleSlice.emit(key);
  }

  formatCount(value: number): string {
    return formatCountUtil(value);
  }
}
