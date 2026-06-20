import { Component, Input, inject, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { StatisticsService } from '../../services/statistics.service';
import { getLaneStateColor } from '../../statistics.constants';
import { LaneSignalData, VramProviderMeta } from '../../statistics.models';
import { EmptyState } from '../empty-state/empty-state';

const STATE_ORDER: Record<string, number> = {
  running: 0,
  loaded: 1,
  starting: 2,
  sleeping: 3,
  cold: 4,
  stopped: 5,
  error: 6,
};

function kvBarColor(pct: number): string {
  if (pct < 50) return 'rgb(var(--color-success-500))';
  if (pct < 80) return 'rgb(var(--color-warning-500))';
  return 'rgb(var(--color-error-500))';
}

function ttftColor(secs: number): string {
  if (secs < 0.2) return 'rgb(var(--color-success-500))';
  if (secs < 0.5) return 'rgb(var(--color-warning-500))';
  return 'rgb(var(--color-error-500))';
}

export interface LaneRow {
  laneId: string;
  lane: LaneSignalData;
  stateColor: string;
  kvColor: string | null;
  ttftColor: string | null;
  ttftLabel: string | null;
}

@Component({
  selector: 'app-stats-lane-health-panel',
  standalone: true,
  imports: [CommonModule, EmptyState],
  templateUrl: './lane-health-panel.html',
  styleUrl: './lane-health-panel.scss',
})
export class LaneHealthPanel {
  @Input() lanesByProvider: Record<string, Record<string, LaneSignalData>> = {};
  @Input() providerMeta: Record<string, VramProviderMeta> = {};
  @Input() selectedProvider: string | null = null;

  private statisticsService = inject(StatisticsService);

  unloadingLaneId = signal<string | null>(null);
  unloadError = signal<string | null>(null);

  get providerName(): string | null {
    return this.selectedProvider ?? Object.keys(this.lanesByProvider)[0] ?? null;
  }

  get lanes(): LaneRow[] {
    const name = this.providerName;
    if (!name) return [];
    const lanesForProvider = this.lanesByProvider[name] ?? {};
    return Object.entries(lanesForProvider)
      .sort(([, a], [, b]) => {
        const aOrder = STATE_ORDER[a.runtime_state] ?? 99;
        const bOrder = STATE_ORDER[b.runtime_state] ?? 99;
        if (aOrder !== bOrder) return aOrder - bOrder;
        return a.model.localeCompare(b.model);
      })
      .map(([laneId, lane]) => {
        const kvPct = lane.gpu_cache_usage_percent;
        const ttft = lane.ttft_p95_seconds;
        return {
          laneId,
          lane,
          stateColor: getLaneStateColor(lane.runtime_state),
          kvColor: kvPct != null ? kvBarColor(kvPct) : null,
          ttftColor: ttft != null ? ttftColor(ttft) : null,
          ttftLabel:
            ttft != null
              ? ttft < 1
                ? `${Math.round(ttft * 1000)}ms`
                : `${ttft.toFixed(2)}s`
              : null,
        };
      });
  }

  get providerId(): number | null {
    const name = this.providerName;
    return name ? (this.providerMeta[name]?.provider_id ?? null) : null;
  }

  get providerOnline(): boolean {
    const name = this.providerName;
    if (!name) return false;
    const meta = this.providerMeta[name];
    return meta?.connection_state !== 'offline' && meta?.connected !== false;
  }

  get canUnload(): boolean {
    return this.providerId != null && this.providerOnline;
  }

  minKvPct(pct: number): number {
    return Math.min(100, pct);
  }

  handleUnload(laneId: string): void {
    const pid = this.providerId;
    if (pid == null || this.unloadingLaneId() != null) return;
    this.unloadingLaneId.set(laneId);
    this.unloadError.set(null);

    this.statisticsService.unloadLane(pid, laneId).subscribe({
      next: () => {
        this.unloadingLaneId.set(null);
      },
      error: (err: { status?: number; error?: { error?: string } }) => {
        this.unloadingLaneId.set(null);
        if (err.status === 404 || err.status === 501 || err.status === 0) {
          this.unloadError.set('Action not available on this server yet.');
        } else {
          const detail = err.error?.error ?? `HTTP ${err.status}`;
          this.unloadError.set(`Unload of ${laneId} failed: ${detail}`);
        }
      },
    });
  }
}
