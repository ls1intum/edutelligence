import { Component, Input } from '@angular/core';
import { CommonModule } from '@angular/common';

import { VramDonutComponent, type DonutSlice } from '../vram-donut/vram-donut';
import { getLaneStateColor, cssVar } from '../../statistics.constants';
import type { LaneSignalData } from '../../statistics.models';

// Sort order mirrors the original lane-vram-pie.web.tsx
const STATE_ORDER: Record<string, number> = {
  running: 0,
  loaded: 1,
  sleeping: 2,
  starting: 3,
  cold: 4,
  stopped: 5,
  error: 6,
};

@Component({
  selector: 'app-stats-lane-vram-pie',
  standalone: true,
  imports: [CommonModule, VramDonutComponent],
  templateUrl: './lane-vram-pie.html',
  styleUrl: './lane-vram-pie.scss',
})
export class LaneVramPieComponent {
  @Input() lanes: Record<string, LaneSignalData> = {};
  @Input() totalVramMb = 0;
  @Input() freeVramMb = 0;

  get slices(): DonutSlice[] {
    const result: DonutSlice[] = [];
    let allocatedMb = 0;

    // Sort lanes by state priority then model name, matching the original tsx
    const sortedLanes = Object.entries(this.lanes).sort(([, a], [, b]) => {
      const ao = STATE_ORDER[a.runtime_state] ?? 99;
      const bo = STATE_ORDER[b.runtime_state] ?? 99;
      if (ao !== bo) return ao - bo;
      return a.model.localeCompare(b.model);
    });

    for (const [, lane] of sortedLanes) {
      const vramMb = lane.effective_vram_mb ?? 0;
      if (vramMb <= 0) continue;
      allocatedMb += vramMb;

      // Shorten model name to last path segment for legend readability
      const shortModel = lane.model.includes('/')
        ? lane.model.split('/').pop()!
        : lane.model;

      result.push({
        value: Number((vramMb / 1024).toFixed(3)),
        color: getLaneStateColor(lane.runtime_state),
        text: `${shortModel} [${lane.runtime_state}]`,
      });
    }

    // "Other used" for unattributed VRAM
    const usedMb = this.totalVramMb - this.freeVramMb;
    const otherUsedMb = Math.max(usedMb - allocatedMb, 0);
    if (otherUsedMb > 0) {
      result.push({
        value: Number((otherUsedMb / 1024).toFixed(3)),
        color: cssVar('--color-primary-800'),
        text: 'Other used',
      });
    }

    // Free slice
    if (this.freeVramMb > 0) {
      result.push({
        value: Number((this.freeVramMb / 1024).toFixed(3)),
        color: cssVar('--color-success-300'),
        text: 'Free',
      });
    }

    return result.filter((s) => s.value > 0);
  }

  get freePct(): number {
    return this.totalVramMb > 0
      ? Math.round((this.freeVramMb / this.totalVramMb) * 100)
      : 0;
  }

  get totalGb(): number {
    return this.totalVramMb / 1024;
  }

  get centerTop(): string {
    return 'Free';
  }

  get centerMiddle(): string {
    return `${this.freePct}%`;
  }

  get centerBottom(): string {
    return `of ${this.totalGb.toFixed(1)} GB`;
  }
}
