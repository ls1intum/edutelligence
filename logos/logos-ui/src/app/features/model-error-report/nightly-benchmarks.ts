import { Component, Input, OnChanges, OnDestroy, inject, signal } from '@angular/core';
import { HttpClient, HttpErrorResponse } from '@angular/common/http';
import { firstValueFrom } from 'rxjs';
import { ModalConfirmComponent } from '../../shared/components/modal/modal-confirm/modal-confirm';

export interface NightlyStatus {
  enabled: boolean;
  status: string;
  recovery_required: boolean;
  last_run_date?: string;
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

  statusLabel(value: string): string {
    const labels: Record<string, string> = {
      scheduled: 'Waiting for tonight', preparing: 'Preparing worker', running: 'Benchmark in progress',
      completed: 'Finished — see results', disabled: 'Deactivated', success: 'Successful', failed: 'Failed',
      stalled: 'Stopped after five minutes without progress', preparation_timeout: 'Preparation timed out',
      window_closed: 'No new runs after 04:50', window_closed_below_half: 'Stopped at 05:00 below 50% complete',
      recovery_required: 'Worker recovery required', interrupted_recovered: 'Interrupted; worker restored',
      interrupted: 'Interrupted', cancelled: 'Cancelled', lease_lost: 'Maintenance ownership lost',
    };
    return labels[value] ?? value;
  }

  review(): void {
    if (!this.state() || this.saving()) return;
    this.expected = this.state()!.enabled;
    this.error.set(null);
    this.confirming.set(true);
  }

  get enabling(): boolean { return !this.expected; }

  get confirmationMessage(): string {
    return this.enabling
      ? `Enable nightly benchmarks for this model on ${this.providerName}? Starts are allowed 03:00–04:50 Europe/Berlin. At 05:00, the current run continues only if at least 50% of requests have completed. Five minutes without output or completed requests stops it, with at most one retry before 04:50. One worker is reserved at a time; another healthy worker must remain available. The fixed workload is GSM8K, 50 requests, 512 max output tokens and concurrency 4. Current settings are the baseline; only known sequence and batch-token limits vary by ±25%. Original settings are restored afterwards. These runs use their own fixed plan, independent of the manual editor.`
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
      this.state.set(state);
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
