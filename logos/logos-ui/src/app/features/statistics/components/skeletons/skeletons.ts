import { Component, Input, ChangeDetectionStrategy } from '@angular/core';

export type SkeletonVariant =
  | 'kpi'
  | 'donut'
  | 'bars'
  | 'lane'
  | 'gpu'
  | 'status'
  | 'area'
  | 'rows';

@Component({
  selector: 'app-stats-skeleton',
  standalone: true,
  templateUrl: './skeletons.html',
  changeDetection: ChangeDetectionStrategy.Eager,
  styleUrls: ['./skeletons.scss'],
})
export class StatsSkeletonComponent {
  @Input() variant: SkeletonVariant = 'kpi';

  // Bar chart heights (fraction of 320px)
  readonly barHeights = [
    0.12, 0.22, 0.18, 0.3, 0.55, 0.84, 0.96, 0.62, 0.4, 0.28, 0.18, 0.1, 0.14, 0.22, 0.3, 0.46, 0.2,
    0.12, 0.08, 0.16, 0.24, 0.44, 0.36, 0.22, 0.14,
  ];

  // Area chart y-fractions (fraction of 280px)
  readonly areaHeights = [0.92, 0.9, 0.88, 0.78, 0.55, 0.4, 0.65, 0.85, 0.91, 0.93, 0.93, 0.92];

  // Lane rows
  readonly laneRows = [0, 1];

  // GPU cards
  readonly gpuCards = [0, 1];

  // Status rows
  readonly statusRows = [80, 30, 12, 8];

  // Legend rows for donut
  readonly legendWidths = [140, 130, 120];

  // Request row widths
  readonly requestRows = [
    { name: 220, age: 56, total: 64, meta: 200 },
    { name: 250, age: 48, total: 70, meta: 220 },
    { name: 195, age: 60, total: 58, meta: 180 },
    { name: 235, age: 52, total: 66, meta: 208 },
    { name: 210, age: 56, total: 60, meta: 196 },
  ];

  barHeightPx(fraction: number): number {
    return Math.max(4, fraction * (320 - 40));
  }

  areaHeightPx(fraction: number): number {
    return Math.max(8, fraction * (280 - 40));
  }
}
