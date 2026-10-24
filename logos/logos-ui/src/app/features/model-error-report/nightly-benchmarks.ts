import { Component, Input, OnChanges, OnDestroy, inject, signal } from '@angular/core';
import { HttpClient, HttpErrorResponse } from '@angular/common/http';
import { firstValueFrom } from 'rxjs';
import { ModalConfirmComponent } from '../../shared/components/modal/modal-confirm/modal-confirm';

export interface NightlyStatus {
  max_maintenance_nodes?: number;
  window?: { start: string; end: string; benchmark_start_cutoff: string; timezone: string };
  enabled: boolean;
  status: string;
  recovery_required: boolean;
  last_run_date?: string;
  plan?: { serving_overrides: Record<string, number | null> }[];
  report: { configuration?: number; attempt?: number; status: string; reason?: string; benchmark_id?: number; job_id?: number }[];
}

@Component({
  selector: 'app-nightly-benchmarks',
  standalone: true,
  imports: [ModalConfirmComponent],
  templateUrl: './nightly-benchmarks.html',
  styleUrl: './nightly-benchmarks.scss',
})
export class NightlyBenchmarks implements OnChanges, OnDestroy {
  @Input({ required: true }) pairId!: number;
  @Input({ required: true }) providerName!: string;
  @Input({ required: true }) modelName!: string;
  private readonly http = inject(HttpClient);
  readonly state = signal<NightlyStatus | null>(null);
  readonly confirming = signal(false);
  readonly saving = signal(false);
  readonly error = signal<string | null>(null);
  private expected = false;
  private version = 0;
  private timer?: ReturnType<typeof setTimeout>;
  private destroyed = false;

  ngOnChanges(): void {
    this.version++;
    this.state.set(null);
    this.confirming.set(false);
    clearTimeout(this.timer);
    void this.refresh();
  }

  ngOnDestroy(): void {
    this.destroyed = true;
    this.version++;
    clearTimeout(this.timer);
  }

  async refresh(): Promise<void> {
    const version = this.version;
    try {
      const state = await firstValueFrom(this.http.post<NightlyStatus>(
        '/api/logosdb/model_benchmarks/nightly/status', { model_provider_id: this.pairId }));
      if (version !== this.version || this.destroyed) return;
      this.state.set(state);
      if (!this.confirming()) this.error.set(null);
    } catch {
      if (version !== this.version || this.destroyed) return;
      this.error.set('Could not load nightly benchmark status.');
    } finally {
      if (version === this.version && !this.destroyed) {
        clearTimeout(this.timer);
        this.timer = setTimeout(() => void this.refresh(), 15000);
      }
    }
  }

  get plannedParameters(): { name: string; values: string }[] {
    const plan = this.state()?.plan ?? [];
    return ['max_num_seqs', 'max_num_batched_tokens'].flatMap(name => {
      const values = [...new Set(plan.flatMap(run => {
        const value = run.serving_overrides[name];
        return typeof value === 'number' ? [value] : [];
      }))].sort((a, b) => a - b);
      return values.length ? [{ name, values: values.join(', ') }] : [];
    });
  }

  get window() {
    return this.state()?.window;
  }

  statusLabel(value: string): string {
    const labels: Record<string, string> = {
      scheduled: 'Waiting in nightly rotation', unavailable: 'Waiting for an available worker', preparing: 'Preparing worker', running: 'Benchmark in progress',
      completed: 'Finished — see results', disabled: 'Deactivated', success: 'Successful', failed: 'Failed',
      stalled: 'Stopped after five minutes without progress', preparation_timeout: 'Preparation timed out',
      window_closed: this.window ? `No new runs after ${this.window.benchmark_start_cutoff}` : 'Benchmark start window closed', window_closed_below_half: this.window ? `Stopped at ${this.window.end} below 50% complete` : 'Stopped below 50% at the maintenance cutoff',
      calibration_pending: 'Waiting for calibration',
      recovery_required: 'Worker recovery required', interrupted_recovered: 'Interrupted; worker restored',
      interrupted: 'Interrupted', cancelled: 'Cancelled', lease_lost: 'Maintenance ownership lost',
    };
    return labels[value] ?? value;
  }

  review(): void {
    if (!this.state() || this.saving() || (!this.state()!.enabled && !this.window)) return;
    this.expected = this.state()!.enabled;
    this.error.set(null);
    this.confirming.set(true);
  }

  get enabling(): boolean { return !this.expected; }

  get confirmationMessage(): string {
    const window = this.window;
    if (this.enabling && !window) return 'The maintenance window is unavailable. Refresh before enabling nightly runs.';
    return this.enabling
      ? `Test ${this.modelName} on ${this.providerName} during ${window!.start}–${window!.end} ${window!.timezone}. The whole worker is reserved during testing and cannot serve production requests. Current settings are measured first, then batching variants. Original settings are restored afterwards.`
      : `Disable nightly benchmarks for this model on ${this.providerName}? Future runs will stop. An active nightly run will be cancelled and its original settings restored before the worker returns to production.`;
  }

  async confirm(): Promise<void> {
    if (!this.confirming() || this.saving()) return;
    const version = ++this.version;
    this.saving.set(true);
    clearTimeout(this.timer);
    try {
      const state = await firstValueFrom(this.http.post<NightlyStatus>(
        '/api/logosdb/model_benchmarks/nightly/configure', {
          model_provider_id: this.pairId, enabled: !this.expected, expected_enabled: this.expected,
        }));
      if (version !== this.version || this.destroyed) return;
      this.state.set({ ...state, plan: state.plan ?? this.state()?.plan, window: state.window ?? this.state()?.window, max_maintenance_nodes: state.max_maintenance_nodes ?? this.state()?.max_maintenance_nodes });
      this.confirming.set(false);
      this.error.set(null);
    } catch (error) {
      if (version !== this.version || this.destroyed) return;
      this.error.set(error instanceof HttpErrorResponse && typeof error.error?.detail === 'string'
        ? error.error.detail : 'Could not change nightly benchmarks. Refresh and try again.');
    } finally {
      this.saving.set(false);
      if (version === this.version && !this.destroyed) this.timer = setTimeout(() => void this.refresh(), 15000);
    }
  }
}
