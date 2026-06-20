import { Component, Input, inject, signal, computed } from '@angular/core';
import { CommonModule } from '@angular/common';
import { StatisticsService } from '../../services/statistics.service';
import { DeviceInfo, LaneSignalData, VramProviderMeta, VramV2Sample } from '../../statistics.models';
import { EmptyState } from '../empty-state/empty-state';

type CalibrateState =
  | { kind: 'idle' }
  | { kind: 'loading' }
  | { kind: 'success'; message: string }
  | { kind: 'error'; message: string };

export function tempColor(temp: number | null): string {
  if (temp === null) return 'rgb(var(--color-typography-400))';
  if (temp < 70) return 'rgb(var(--color-success-500))';
  if (temp < 85) return 'rgb(var(--color-warning-500))';
  return 'rgb(var(--color-error-500))';
}

export function formatMb(mb: number): string {
  if (mb >= 1024) return `${(mb / 1024).toFixed(1)} GB`;
  return `${Math.round(mb)} MB`;
}

@Component({
  selector: 'app-stats-worker-gpu-panel',
  standalone: true,
  imports: [CommonModule, EmptyState],
  templateUrl: './worker-gpu-panel.html',
  styleUrl: './worker-gpu-panel.scss',
})
export class WorkerGpuPanel {
  @Input() providerLatestSamples: Record<string, VramV2Sample | null> = {};
  @Input() providerDevices: Record<string, DeviceInfo[]> = {};
  @Input() providerMeta: Record<string, VramProviderMeta> = {};
  @Input() lanesByProvider: Record<string, Record<string, LaneSignalData>> = {};
  @Input() activeProvider: string | null = null;

  private statisticsService = inject(StatisticsService);

  calibrateState = signal<CalibrateState>({ kind: 'idle' });

  // Sorted providers: online-first, then alphabetical
  get providers(): string[] {
    return Object.keys(this.providerLatestSamples).sort((a, b) => {
      const aOnline = this.isOnline(a);
      const bOnline = this.isOnline(b);
      if (aOnline !== bOnline) return aOnline ? -1 : 1;
      return a.localeCompare(b);
    });
  }

  get resolvedActiveProvider(): string | null {
    const providers = this.providers;
    if (this.activeProvider && providers.includes(this.activeProvider)) {
      return this.activeProvider;
    }
    return providers[0] ?? null;
  }

  private isOnline(provider: string): boolean {
    const meta = this.providerMeta[provider];
    return meta?.connection_state !== 'offline' && meta?.connected !== false;
  }

  get isOffline(): boolean {
    const active = this.resolvedActiveProvider;
    if (!active) return false;
    return !this.isOnline(active);
  }

  get latestSample(): VramV2Sample | null {
    const active = this.resolvedActiveProvider;
    return active ? (this.providerLatestSamples[active] ?? null) : null;
  }

  get devices(): DeviceInfo[] {
    const active = this.resolvedActiveProvider;
    if (active && this.providerDevices[active]?.length) {
      return this.providerDevices[active];
    }
    const fromSignal = this.latestSample?.scheduler_signals?.provider?.devices;
    if (Array.isArray(fromSignal) && fromSignal.length) return fromSignal;
    return [];
  }

  get providerSignals() {
    return this.latestSample?.scheduler_signals?.provider ?? null;
  }

  get nvidiaAvailable(): boolean {
    return this.providerSignals?.nvidia_smi_available ?? true;
  }

  get deviceMode(): string | null {
    return this.providerSignals?.device_mode ?? null;
  }

  get isDerived(): boolean {
    return this.deviceMode === 'derived' || !this.nvidiaAvailable;
  }

  get laneCount(): number {
    const active = this.resolvedActiveProvider ?? '';
    return Object.keys(this.lanesByProvider[active] ?? {}).length;
  }

  get loadedLanes(): number {
    return this.providerSignals?.loaded_lane_count ?? 0;
  }

  get activeLanes(): number {
    const active = this.resolvedActiveProvider ?? '';
    return Object.values(this.lanesByProvider[active] ?? {}).filter(
      (l) => l.runtime_state === 'running' || l.active_requests > 0
    ).length;
  }

  get activeProviderId(): number | null {
    const active = this.resolvedActiveProvider;
    return active ? (this.providerMeta[active]?.provider_id ?? null) : null;
  }

  get canCalibrate(): boolean {
    return this.activeProviderId != null && !this.isOffline;
  }

  usedPct(device: DeviceInfo): number {
    if (device.memory_total_mb <= 0) return 0;
    return Math.min(100, (device.memory_used_mb / device.memory_total_mb) * 100);
  }

  syntheticUsedMb(): number {
    return this.providerSignals?.used_memory_mb ?? 0;
  }

  syntheticTotalMb(): number {
    return this.providerSignals?.total_memory_mb ?? 0;
  }

  syntheticFreeMb(): number {
    return this.providerSignals?.free_memory_mb ?? 0;
  }

  syntheticPct(): number {
    const total = this.syntheticTotalMb();
    if (total <= 0) return 0;
    return Math.min(100, (this.syntheticUsedMb() / total) * 100);
  }

  deviceName(device: DeviceInfo): string {
    return device.name || device.device_id;
  }

  tempColor = tempColor;
  formatMb = formatMb;

  handleCalibrateUncalibrated(): void {
    const pid = this.activeProviderId;
    if (pid == null) return;
    this.calibrateState.set({ kind: 'loading' });

    this.statisticsService.calibrateUncalibrated(pid).subscribe({
      next: (body) => {
        const count = typeof body?.count === 'number' ? body.count : 0;
        const models = Array.isArray(body?.models) ? (body.models as string[]) : [];
        const message =
          count === 0
            ? 'No uncalibrated models on this worker.'
            : `Calibrating ${count} model(s): ${models.join(', ')}`;
        this.calibrateState.set({ kind: 'success', message });
      },
      error: (err: { status?: number; error?: { error?: string } }) => {
        if (err.status === 404 || err.status === 501 || err.status === 0) {
          this.calibrateState.set({ kind: 'error', message: 'Action not available on this server yet.' });
        } else {
          const detail = err.error?.error ?? `HTTP ${err.status}`;
          this.calibrateState.set({ kind: 'error', message: detail });
        }
      },
    });
  }
}
