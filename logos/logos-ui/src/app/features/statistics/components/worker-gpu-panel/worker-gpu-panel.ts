import {
  Component,
  Input,
  OnChanges,
  SimpleChanges,
  inject,
  signal,
  computed,
  ChangeDetectionStrategy,
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { StatisticsService } from '../../services/statistics.service';
import {
  DeviceInfo,
  LaneSignalData,
  VramProviderMeta,
  VramV2Sample,
} from '../../statistics.models';
import { EmptyState } from '../empty-state/empty-state';

type CalibrateState =
  | { kind: 'idle' }
  | { kind: 'loading' }
  | { kind: 'success'; message: string }
  | { kind: 'error'; message: string };

export function tempColor(temp: number | null): string {
  if (temp === null) return 'rgb(var(--color-typography-500))';
  if (temp < 70) return 'rgb(var(--color-success))';
  if (temp < 85) return 'rgb(var(--color-warning))';
  return 'rgb(var(--color-error))';
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
  changeDetection: ChangeDetectionStrategy.Eager,
  styleUrl: './worker-gpu-panel.scss',
})
export class WorkerGpuPanel implements OnChanges {
  @Input() providerLatestSamples: Record<string, VramV2Sample | null> = {};
  @Input() providerDevices: Record<string, DeviceInfo[]> = {};
  @Input() providerMeta: Record<string, VramProviderMeta> = {};
  @Input() lanesByProvider: Record<string, Record<string, LaneSignalData>> = {};
  @Input() activeProvider: string | null = null;

  private statisticsService = inject(StatisticsService);

  calibrateState = signal<CalibrateState>({ kind: 'idle' });
  /** Worker the in-flight calibrate call was started on — its answer must not
   *  land under a worker the operator has moved on to. */
  private calibrateProvider: string | null = null;
  /** The resolved worker the last input change settled on. */
  private resolvedProvider: string | null = null;

  ngOnChanges(_changes: SimpleChanges): void {
    const resolved = this.resolvedActiveProvider;
    if (resolved === this.resolvedProvider) return;
    // The state is the answer to an action on *one* worker: "Calibrating 2
    // model(s): …" said on worker A means nothing under worker B's panel, so
    // a worker change drops it instead of letting it hang around. Compared
    // against the *resolved* worker, not the raw selection: with no explicit
    // selection the panel falls back to the first provider, and that fallback
    // can change on its own — a worker leaves the list or goes offline — even
    // though activeProvider itself never changed.
    this.calibrateState.set({ kind: 'idle' });
    this.calibrateProvider = null;
    this.resolvedProvider = resolved;
  }

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
      (l) => l.runtime_state === 'running' || l.active_requests > 0,
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

  async handleCalibrateUncalibrated(): Promise<void> {
    const pid = this.activeProviderId;
    const active = this.resolvedActiveProvider;
    if (pid == null || active == null) return;
    this.calibrateProvider = active;
    this.calibrateState.set({ kind: 'loading' });

    try {
      const body = await this.statisticsService.calibrateUncalibrated(pid);
      // The operator can switch workers while the call is in flight — or the
      // fallback worker can change under a null selection — and the answer
      // belongs to the worker it was asked for, so a stale one is dropped
      // rather than shown under the panel the operator is looking at now.
      if (this.calibrateProvider !== active || this.resolvedActiveProvider !== active) return;
      const count = typeof body?.count === 'number' ? body.count : 0;
      const models = Array.isArray(body?.models) ? (body.models as string[]) : [];
      const message =
        count === 0
          ? 'No uncalibrated models on this worker.'
          : `Calibrating ${count} model(s): ${models.join(', ')}`;
      this.calibrateState.set({ kind: 'success', message });
    } catch (err: unknown) {
      if (this.calibrateProvider !== active || this.resolvedActiveProvider !== active) return;
      const e = err as { status?: number; error?: { error?: string } };
      if (e.status === 404 || e.status === 501 || e.status === 0) {
        this.calibrateState.set({
          kind: 'error',
          message: 'Action not available on this server yet.',
        });
      } else {
        const detail = e.error?.error ?? `HTTP ${e.status}`;
        this.calibrateState.set({ kind: 'error', message: detail });
      }
    }
  }
}
