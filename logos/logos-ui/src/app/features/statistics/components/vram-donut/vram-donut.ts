import { Component, Input, computed, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { donutArc } from '../../statistics.utils';

export interface DonutSlice {
  value: number;
  color: string;
  text: string;
}

interface ComputedSlice extends DonutSlice {
  startAngle: number;
  endAngle: number;
  percentage: number;
}

@Component({
  selector: 'app-stats-vram-donut',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './vram-donut.html',
  styleUrl: './vram-donut.scss',
})
export class VramDonutComponent {
  @Input() data: DonutSlice[] = [];
  @Input() centerTop?: string;
  @Input() centerMiddle?: string;
  @Input() centerBottom?: string;
  @Input() valueSuffix = '';
  @Input() valueDecimals = 0;

  hoveredIndex = signal<number | null>(null);

  get computedSlices(): ComputedSlice[] {
    const total = this.data.reduce((sum, s) => sum + s.value, 0);
    if (total === 0) return [];

    let cumAngle = 0;
    const TWO_PI = 2 * Math.PI;

    return this.data.map((slice) => {
      const fraction = slice.value / total;
      const startAngle = cumAngle;
      const endAngle = cumAngle + fraction * TWO_PI;
      cumAngle = endAngle;
      return {
        ...slice,
        startAngle,
        endAngle,
        percentage: Math.round(fraction * 100),
      };
    });
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
}
