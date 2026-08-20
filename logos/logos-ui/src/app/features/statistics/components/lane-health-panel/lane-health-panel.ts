import {
  Component,
  Input,
  OnChanges,
  SimpleChanges,
  inject,
  signal,
  ChangeDetectionStrategy,
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { StatisticsService, ProviderModel } from '../../services/statistics.service';
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
  if (pct < 50) return 'rgb(var(--color-success))';
  if (pct < 80) return 'rgb(var(--color-warning))';
  return 'rgb(var(--color-error))';
}

function ttftColor(secs: number): string {
  if (secs < 0.2) return 'rgb(var(--color-success))';
  if (secs < 0.5) return 'rgb(var(--color-warning))';
  return 'rgb(var(--color-error))';
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
  changeDetection: ChangeDetectionStrategy.Eager,
  styleUrl: './lane-health-panel.scss',
})
export class LaneHealthPanel implements OnChanges {
  @Input() lanesByProvider: Record<string, Record<string, LaneSignalData>> = {};
  @Input() providerMeta: Record<string, VramProviderMeta> = {};
  @Input() selectedProvider: string | null = null;

  private statisticsService = inject(StatisticsService);

  unloadingLaneId = signal<string | null>(null);
  unloadError = signal<string | null>(null);

  // ── Load-lane state ──────────────────────────────────────────────────────
  pickerOpen = signal(false);
  modelsLoading = signal(false);
  loadModels = signal<ProviderModel[]>([]);
  selectedModel = signal<string | null>(null);
  addingLane = signal(false);
  addError = signal<string | null>(null);
  /** Fetched model lists, keyed by provider id — never shared across providers. */
  private readonly modelsByProvider = new Map<number, ProviderModel[]>();
  private readonly modelsInFlight = new Set<number>();
  /** Provider the currently visible picker state belongs to. */
  private pickerProviderId: number | null = null;

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

  /** "GPU 0-1 · ×4" style placement line; null when the lane reports none. */
  gpuLabel(lane: LaneSignalData): string | null {
    const gpu = (lane.effective_gpu_devices || lane.gpu_devices || '').trim();
    const np = lane.num_parallel;
    const parts: string[] = [];
    if (gpu) parts.push(`GPU ${gpu}`);
    if (np != null && np > 1) parts.push(`×${np}`);
    return parts.length > 0 ? parts.join(' · ') : null;
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

  /** Lane actions need a resolved provider that is actually reachable. */
  get canUnload(): boolean {
    return this.providerId != null && this.providerOnline;
  }

  get canAdd(): boolean {
    return this.canUnload;
  }

  /** Models that don't already have a lane (lanes are keyed by model name). */
  get loadableModels(): ProviderModel[] {
    const name = this.providerName;
    const lanes = name ? (this.lanesByProvider[name] ?? {}) : {};
    const loaded = new Set(Object.values(lanes).map((l) => (l.model ?? '').trim().toLowerCase()));
    return this.loadModels().filter(
      (m) => m.model_name && !loaded.has(m.model_name.trim().toLowerCase()),
    );
  }

  minKvPct(pct: number): number {
    return Math.min(100, pct);
  }

  async handleUnload(laneId: string): Promise<void> {
    const pid = this.providerId;
    if (pid == null || this.unloadingLaneId() != null) return;
    this.unloadingLaneId.set(laneId);
    this.unloadError.set(null);

    try {
      await this.statisticsService.unloadLane(pid, laneId);
      this.unloadingLaneId.set(null);
    } catch (err: unknown) {
      this.unloadingLaneId.set(null);
      const e = err as { status?: number; error?: { error?: string } };
      if (e.status === 404 || e.status === 501 || e.status === 0) {
        this.unloadError.set('Action not available on this server yet.');
      } else {
        const detail = e.error?.error ?? `HTTP ${e.status}`;
        this.unloadError.set(`Unload of ${laneId} failed: ${detail}`);
      }
    }
  }

  // ── Load-lane handlers ───────────────────────────────────────────────────

  openPicker(): void {
    this.pickerOpen.set(true);
    this.addError.set(null);
    const pid = this.providerId;
    this.pickerProviderId = pid;
    if (pid == null) {
      this.loadModels.set([]);
      this.modelsLoading.set(false);
      return;
    }

    // Show whatever we already have for *this* provider, never another one's.
    this.loadModels.set(this.modelsByProvider.get(pid) ?? []);
    if (this.modelsByProvider.has(pid)) {
      this.modelsLoading.set(false);
      return;
    }
    if (this.modelsInFlight.has(pid)) {
      this.modelsLoading.set(true);
      return;
    }

    this.modelsInFlight.add(pid);
    this.modelsLoading.set(true);
    this.statisticsService
      .getProviderModels(pid)
      .then((models) => {
        this.modelsByProvider.set(pid, models ?? []);
        // Discard the response if the operator moved on to another provider.
        if (this.pickerProviderId === pid) this.loadModels.set(models ?? []);
      })
      .catch((err: unknown) => {
        const e = err as { error?: { error?: string } };
        if (this.pickerProviderId === pid) {
          this.addError.set(`Could not load models: ${e?.error?.error ?? 'unknown error'}`);
        }
      })
      .finally(() => {
        this.modelsInFlight.delete(pid);
        if (this.pickerProviderId === pid) this.modelsLoading.set(false);
      });
  }

  closePicker(): void {
    this.pickerOpen.set(false);
    this.selectedModel.set(null);
    this.addError.set(null);
    this.pickerProviderId = null;
  }

  ngOnChanges(changes: SimpleChanges): void {
    // The provider dropdown lives outside this component: when it moves, the
    // open picker still holds the previous provider's models and selection,
    // and submitting it would load a model onto a provider that never served it.
    if (changes['selectedProvider'] && this.pickerProviderId !== this.providerId) {
      this.closePicker();
      this.loadModels.set([]);
      this.modelsLoading.set(false);
    }
  }

  selectModel(event: Event): void {
    const value = (event.target as HTMLSelectElement).value;
    this.selectedModel.set(value || null);
  }

  async handleAddLane(): Promise<void> {
    const pid = this.providerId;
    const model = this.selectedModel();
    if (pid == null || model == null || this.addingLane()) return;
    // Guard against a provider switch between picking and submitting.
    if (this.pickerProviderId !== pid || !this.loadModels().some((m) => m.model_name === model)) {
      this.addError.set('The provider changed — reopen the picker and select a model again.');
      return;
    }
    this.addingLane.set(true);
    this.addError.set(null);
    try {
      await this.statisticsService.addLane(pid, model);
      this.addingLane.set(false);
      this.closePicker();
    } catch (err: unknown) {
      this.addingLane.set(false);
      const e = err as { status?: number; error?: { error?: string } };
      const detail = e.error?.error ?? `HTTP ${e.status}`;
      this.addError.set(`Loading ${model} failed: ${detail}`);
    }
  }
}
