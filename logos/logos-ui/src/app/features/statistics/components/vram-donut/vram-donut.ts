import {
  Component,
  EventEmitter,
  Input,
  Output,
  signal,
  ChangeDetectionStrategy,
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { donutArc } from '../../statistics.utils';

export interface DonutSlice {
  value: number;
  color: string;
  text: string;
  /** Left out of the ring; with {@link VramDonutComponent.toggleable} it stays in the legend, unticked. */
  hidden?: boolean;
}

interface ComputedSlice extends DonutSlice {
  /** Position in {@link VramDonutComponent.data}, so hover and toggles survive hidden slices. */
  dataIndex: number;
  startAngle: number;
  endAngle: number;
  percentage: number;
}

@Component({
  selector: 'app-stats-vram-donut',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './vram-donut.html',
  changeDetection: ChangeDetectionStrategy.Eager,
  styleUrl: './vram-donut.scss',
})
export class VramDonutComponent {
  @Input() data: DonutSlice[] = [];
  @Input() centerTop?: string;
  @Input() centerMiddle?: string;
  @Input() centerBottom?: string;
  @Input() valueSuffix = '';
  @Input() valueDecimals = 0;
  /**
   * Legend rows become checkboxes: every slice stays listed, and ticking one
   * emits {@link toggleSlice} with its index in {@link data}. The parent flips
   * its `hidden` flag; the ring re-partitions over what is left.
   */
  @Input() toggleable = false;
  @Output() toggleSlice = new EventEmitter<number>();

  /** Index into {@link data}, not into {@link computedSlices}. */
  hoveredIndex = signal<number | null>(null);

  get computedSlices(): ComputedSlice[] {
    const visible = this.data
      .map((slice, dataIndex) => ({ slice, dataIndex }))
      .filter((v) => !v.slice.hidden);
    const total = visible.reduce((sum, v) => sum + v.slice.value, 0);
    if (total === 0) return [];

    let cumAngle = 0;
    const TWO_PI = 2 * Math.PI;

    return visible.map(({ slice, dataIndex }) => {
      const fraction = slice.value / total;
      const startAngle = cumAngle;
      const endAngle = cumAngle + fraction * TWO_PI;
      cumAngle = endAngle;
      return {
        ...slice,
        dataIndex,
        startAngle,
        endAngle,
        percentage: Math.round(fraction * 100),
      };
    });
  }

  get hoveredSlice(): ComputedSlice | undefined {
    const index = this.hoveredIndex();
    return index === null ? undefined : this.computedSlices.find((s) => s.dataIndex === index);
  }

  /** Rows of the legend: every slice when toggleable, otherwise the drawn ones. */
  get legendSlices(): (DonutSlice & { dataIndex: number; percentage?: number })[] {
    if (!this.toggleable) return this.computedSlices;
    const drawn = new Map(this.computedSlices.map((s) => [s.dataIndex, s.percentage]));
    return this.data.map((slice, dataIndex) => ({
      ...slice,
      dataIndex,
      percentage: drawn.get(dataIndex),
    }));
  }

  getArcPath(slice: ComputedSlice): string {
    return donutArc(100, 100, 90, 55, slice.startAngle, slice.endAngle);
  }

  formatValue(value: number): string {
    return value.toFixed(this.valueDecimals) + this.valueSuffix;
  }

  onSliceHover(index: number): void {
    this.hoveredIndex.set(index);
  }

  onSliceLeave(): void {
    this.hoveredIndex.set(null);
  }

  isHovered(index: number): boolean {
    return this.hoveredIndex() === index;
  }

  isAnyHovered(): boolean {
    return this.hoveredIndex() !== null;
  }

  toggle(index: number): void {
    this.toggleSlice.emit(index);
  }
}
