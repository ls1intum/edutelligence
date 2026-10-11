import { ChangeDetectionStrategy, Component, Input } from '@angular/core';
import { CommonModule } from '@angular/common';

import { getLaneStateColor } from '../../statistics.constants';
import type { DeviceInfo, LaneSignalData } from '../../statistics.models';

/** Lane order inside a card: busiest first, so the eye lands on what serves traffic. */
const STATE_ORDER: Record<string, number> = {
  running: 0,
  loaded: 1,
  starting: 2,
  sleeping: 3,
  cold: 4,
  stopped: 5,
  error: 6,
};

/** Every state a lane can be in, in legend order. */
export const LANE_STATES = ['running', 'loaded', 'starting', 'sleeping', 'error'] as const;

export interface MemorySegment {
  laneId: string;
  model: string;
  state: string;
  color: string;
  mb: number;
  /** Share of the card's capacity, 0-100. */
  pct: number;
  /** The lane spans more than one GPU (tensor parallel), so this is its share of it. */
  shared: boolean;
  /** Other GPUs of the same lane, for the hover text. */
  gpuLabel: string | null;
  activeRequests: number;
}

export interface MemoryCard {
  key: string;
  title: string;
  subtitle: string;
  totalMb: number;
  usedMb: number;
  freeMb: number;
  /** What the lanes do not account for: other processes, the OS, the worker itself. */
  otherMb: number;
  segments: MemorySegment[];
  temperatureC: number | null;
  powerW: number | null;
  utilizationPct: number | null;
}


/**
 * "0", "0,1", "0-1" and "0,2-3" all name GPUs; anything else names none. Lane
 * placements come from the worker as free text, and a lane without a readable
 * placement must not be pinned to a card by guesswork.
 */
export function parseGpuIndices(raw: string | null | undefined): number[] {
  const text = (raw ?? '').trim();
  if (!text) return [];
  const out = new Set<number>();
  for (const part of text.split(',')) {
    const range = part.trim().match(/^(\d+)(?:\s*-\s*(\d+))?$/);
    if (!range) return [];
    const from = Number(range[1]);
    const to = range[2] === undefined ? from : Number(range[2]);
    if (to < from || to - from > 64) return [];
    for (let i = from; i <= to; i++) out.add(i);
  }
  return [...out].sort((a, b) => a - b);
}

export function shortModelName(model: string): string {
  return model.includes('/') ? model.split('/').pop()! : model;
}

function formatGb(mb: number): string {
  return mb >= 1024 ? `${(mb / 1024).toFixed(1)} GB` : `${Math.round(mb)} MB`;
}

/**
 * One card per GPU, one bar per card: which lane sits on which card, what
 * state it is in, and how much of that card it holds.
 *
 * Colour carries exactly one meaning on the bars — the lane's runtime state,
 * the same colour the lane list uses. What is not a lane is neutral and never
 * a state colour: other used memory is hatched grey, free memory is the empty
 * track. The legend above the cards is the only key on the page.
 */
@Component({
  selector: 'app-stats-gpu-map',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './gpu-map.html',
  changeDetection: ChangeDetectionStrategy.Eager,
  styleUrl: './gpu-map.scss',
})
export class GpuMapComponent {
  @Input() devices: DeviceInfo[] = [];
  @Input() lanes: Record<string, LaneSignalData> = {};
  /** Apple Silicon: one pool, no GPUs — the host RAM is the memory. */
  @Input() unified = false;
  @Input() offline = false;

  readonly legend = LANE_STATES.map((state) => ({ state, color: getLaneStateColor(state) }));

  private sortedLanes(): Array<[string, LaneSignalData]> {
    return Object.entries(this.lanes).sort(([, a], [, b]) => {
      const ao = STATE_ORDER[a.runtime_state] ?? 99;
      const bo = STATE_ORDER[b.runtime_state] ?? 99;
      if (ao !== bo) return ao - bo;
      return a.model.localeCompare(b.model);
    });
  }

  private placement(lane: LaneSignalData): number[] {
    const parsed = parseGpuIndices(lane.effective_gpu_devices || lane.gpu_devices);
    if (parsed.length) return parsed;
    // A single-GPU worker can only mean that card.
    return this.devices.length === 1 ? [0] : [];
  }

  private segment(
    laneId: string,
    lane: LaneSignalData,
    mb: number,
    totalMb: number,
    gpus: number[],
  ): MemorySegment {
    return {
      laneId,
      model: shortModelName(lane.model),
      state: lane.runtime_state,
      color: getLaneStateColor(lane.runtime_state),
      mb,
      pct: totalMb > 0 ? Math.min((mb / totalMb) * 100, 100) : 0,
      shared: gpus.length > 1,
      gpuLabel: gpus.length ? `GPU ${gpus.join(', ')}` : null,
      activeRequests: lane.active_requests ?? 0,
    };
  }

  get cards(): MemoryCard[] {
    if (this.unified) return [];
    return this.devices.map((device, index) => {
      const segments: MemorySegment[] = [];
      for (const [laneId, lane] of this.sortedLanes()) {
        const gpus = this.placement(lane);
        if (!gpus.includes(index)) continue;
        const total = lane.effective_vram_mb ?? 0;
        if (total <= 0) continue;
        // A tensor-parallel lane holds an even share of its weights per card.
        segments.push(
          this.segment(laneId, lane, total / gpus.length, device.memory_total_mb, gpus),
        );
      }
      const laneMb = segments.reduce((sum, s) => sum + s.mb, 0);
      const usedMb = device.memory_used_mb;
      return {
        key: `gpu-${index}`,
        title: `GPU ${index}`,
        subtitle: device.name,
        totalMb: device.memory_total_mb,
        usedMb,
        freeMb: Math.max(device.memory_total_mb - usedMb, 0),
        otherMb: Math.max(usedMb - laneMb, 0),
        segments,
        temperatureC: device.temperature_celsius,
        powerW: device.power_draw_watts,
        utilizationPct: device.utilization_percent,
      };
    });
  }

  /** Lanes that report no readable placement on a multi-GPU worker. */
  get unplacedLanes(): Array<{ laneId: string; model: string; state: string; color: string }> {
    if (this.unified || this.devices.length < 2) return [];
    return this.sortedLanes()
      .filter(([, lane]) => this.placement(lane).length === 0)
      .map(([laneId, lane]) => ({
        laneId,
        model: shortModelName(lane.model),
        state: lane.runtime_state,
        color: getLaneStateColor(lane.runtime_state),
      }));
  }

  pct(mb: number, total: number): number {
    return total > 0 ? Math.min((mb / total) * 100, 100) : 0;
  }

  gb(mb: number): string {
    return formatGb(mb);
  }

  /** Hot GPUs turn amber then red; the thresholds match the old device card. */
  tempClass(temp: number | null): string {
    if (temp === null) return '';
    if (temp < 70) return 'gpu-map__chip--ok';
    if (temp < 85) return 'gpu-map__chip--warn';
    return 'gpu-map__chip--hot';
  }

  segmentTitle(seg: MemorySegment): string {
    const where = seg.shared && seg.gpuLabel ? ` · spans ${seg.gpuLabel}` : '';
    return `${seg.model} · ${seg.laneId} · ${seg.state} · ${formatGb(seg.mb)}${where}`;
  }
}
