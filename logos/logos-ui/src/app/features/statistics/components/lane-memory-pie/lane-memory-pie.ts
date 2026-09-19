import { Component, Input, ChangeDetectionStrategy } from '@angular/core';
import { CommonModule } from '@angular/common';

import { VramDonutComponent, type DonutSlice } from '../vram-donut/vram-donut';
import { getLaneStateColor, seriesColor } from '../../statistics.constants';
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

/** Which of a lane's two memory footprints the donut breaks down. */
export type LaneMemoryMetric = 'vram' | 'ram';

/**
 * A provider's memory, split by the model occupying it.
 *
 * Serves both GPU memory and host RAM, because they are the same picture drawn
 * from two lane fields: a slice per lane coloured by its runtime state, then
 * whatever of the used total the lanes do not account for, then what is free.
 * Host RAM earns the same view as VRAM — sleeping lanes keep their weights in
 * it and the worker's model cache draws from it, so "which model is holding the
 * host's memory" is as real a question as it is for the GPU.
 */
@Component({
  selector: 'app-stats-lane-memory-pie',
  standalone: true,
  imports: [CommonModule, VramDonutComponent],
  templateUrl: './lane-memory-pie.html',
  changeDetection: ChangeDetectionStrategy.Eager,
  styleUrl: './lane-memory-pie.scss',
})
export class LaneMemoryPieComponent {
  @Input() lanes: Record<string, LaneSignalData> = {};
  @Input() metric: LaneMemoryMetric = 'vram';
  @Input() totalMb = 0;
  @Input() freeMb = 0;

  /**
   * A lane's share of the metric, or null when the worker reports nothing for
   * it. Null and zero are kept apart on purpose: a worker that cannot read
   * process memory reports no host RAM at all, and folding that into 0 would
   * draw a lane as using none rather than leaving it out.
   */
  private laneValueMb(lane: LaneSignalData): number | null {
    if (this.metric === 'ram') {
      return typeof lane.host_ram_mb === 'number' ? lane.host_ram_mb : null;
    }
    return lane.effective_vram_mb ?? null;
  }

  get emptyMessage(): string {
    return this.metric === 'ram' ? 'No RAM data available' : 'No VRAM data available';
  }

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

    for (const [laneId, lane] of sortedLanes) {
      const valueMb = this.laneValueMb(lane);
      if (valueMb === null || valueMb <= 0) continue;
      allocatedMb += valueMb;

      // Shorten model name to last path segment for legend readability.
      // Include laneId so two deployments of the same model stay distinguishable.
      const shortModel = lane.model.includes('/') ? lane.model.split('/').pop()! : lane.model;

      result.push({
        value: Number((valueMb / 1024).toFixed(3)),
        color: getLaneStateColor(lane.runtime_state),
        text: `${shortModel} · ${laneId} [${lane.runtime_state}]`,
      });
    }

    // Whatever of the used total the lanes do not account for: the operating
    // system and the worker itself for RAM, other processes on the card for VRAM.
    const usedMb = this.totalMb - this.freeMb;
    const otherUsedMb = Math.max(usedMb - allocatedMb, 0);
    if (otherUsedMb > 0) {
      result.push({
        value: Number((otherUsedMb / 1024).toFixed(3)),
        color: seriesColor(3), // orange, unused by lane state colors
        text: 'Other used',
      });
    }

    // Free slice
    if (this.freeMb > 0) {
      result.push({
        value: Number((this.freeMb / 1024).toFixed(3)),
        color: seriesColor(4), // pink, unused by lane state colors
        text: 'Free',
      });
    }

    return result.filter((s) => s.value > 0);
  }

  get freePct(): number {
    return this.totalMb > 0 ? Math.round((this.freeMb / this.totalMb) * 100) : 0;
  }

  get totalGb(): number {
    return this.totalMb / 1024;
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
