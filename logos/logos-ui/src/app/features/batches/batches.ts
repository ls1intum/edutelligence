import {
  ChangeDetectionStrategy,
  Component,
  OnDestroy,
  OnInit,
  computed,
  inject,
  signal,
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { BatchKey, BatchObject, BatchService } from '../../core/services/batch.service';

/** Batch states the provider (or Logos) will not move away from on its own. */
const TERMINAL = new Set(['completed', 'failed', 'expired', 'cancelled']);

/**
 * Start a batch, watch it run, take the results.
 *
 * Most batches are driven from a script — upload, poll every few minutes,
 * chain the next one onto the result. This page is for the other half of the
 * job: starting one without writing code, and seeing where a running one got
 * to. It polls on the same cadence a script would, so a batch started here and
 * a batch started from a terminal look identical.
 */
@Component({
  selector: 'app-batches',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './batches.html',
  styleUrl: './batches.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class Batches implements OnInit, OnDestroy {
  private batchService = inject(BatchService);

  keys = signal<BatchKey[]>([]);
  selectedKeyId = signal<number | null>(null);
  batches = signal<BatchObject[]>([]);
  loading = signal(false);
  uploading = signal(false);
  error = signal<string | null>(null);
  notice = signal<string | null>(null);

  file = signal<File | null>(null);
  endpoint = signal('/v1/chat/completions');
  execution = signal('auto');

  /** A batch still moving is worth polling for; a finished one is not. */
  hasRunning = computed(() => this.batches().some(batch => !TERMINAL.has(batch.status)));

  private pollHandle: ReturnType<typeof setInterval> | null = null;

  async ngOnInit(): Promise<void> {
    try {
      const keys = await this.batchService.getKeys();
      this.keys.set(keys);
      if (keys.length > 0) {
        this.selectedKeyId.set(keys[0].id);
        await this.refresh();
      }
    } catch {
      this.error.set('Could not load your API keys.');
    }
    // A batch is minutes-to-hours work, so this is deliberately unhurried;
    // it exists so an open tab keeps up, not to drive the workload.
    this.pollHandle = setInterval(() => {
      if (this.hasRunning()) {
        void this.refresh(true);
      }
    }, 30_000);
  }

  ngOnDestroy(): void {
    if (this.pollHandle) {
      clearInterval(this.pollHandle);
    }
  }

  onKeyChange(value: string): void {
    this.selectedKeyId.set(Number(value));
    void this.refresh();
  }

  onFileSelected(event: Event): void {
    const input = event.target as HTMLInputElement;
    this.file.set(input.files && input.files.length > 0 ? input.files[0] : null);
  }

  async refresh(quiet = false): Promise<void> {
    const keyId = this.selectedKeyId();
    if (keyId === null) return;
    if (!quiet) this.loading.set(true);
    try {
      const response = await this.batchService.list(keyId);
      // The key may have changed while the request was in flight; a stale
      // answer must not replace the new key's list.
      if (this.selectedKeyId() !== keyId) return;
      this.batches.set(response.data ?? []);
      this.error.set(null);
    } catch {
      if (this.selectedKeyId() !== keyId) return;
      if (!quiet) this.error.set('Could not load your batches.');
    } finally {
      if (this.selectedKeyId() === keyId) this.loading.set(false);
    }
  }

  async submit(): Promise<void> {
    const keyId = this.selectedKeyId();
    const file = this.file();
    if (keyId === null || !file) return;

    this.uploading.set(true);
    this.error.set(null);
    this.notice.set(null);
    try {
      const created = await this.batchService.create(keyId, file, this.endpoint(), this.execution());
      this.notice.set(
        created.logos_execution === 'logos'
          ? `Batch ${created.id} queued — Logos runs it here as low-priority requests.`
          : `Batch ${created.id} handed to the provider's batch endpoint.`,
      );
      this.file.set(null);
      await this.refresh();
    } catch (err: unknown) {
      // The orchestrator's message names the offending line or model, which is
      // the only useful thing to show here.
      this.error.set(this.messageOf(err) ?? 'The batch could not be started.');
    } finally {
      this.uploading.set(false);
    }
  }

  async cancel(batch: BatchObject): Promise<void> {
    const keyId = this.selectedKeyId();
    if (keyId === null) return;
    try {
      await this.batchService.cancel(keyId, batch.id);
      await this.refresh();
    } catch (err: unknown) {
      this.error.set(this.messageOf(err) ?? 'The batch could not be cancelled.');
    }
  }

  async download(batch: BatchObject): Promise<void> {
    const keyId = this.selectedKeyId();
    if (keyId === null || !batch.output_file_id) return;
    try {
      const blob = await this.batchService.results(keyId, batch.id, batch.output_file_id);
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement('a');
      anchor.href = url;
      anchor.download = `${batch.id}_results.jsonl`;
      anchor.click();
      URL.revokeObjectURL(url);
    } catch (err: unknown) {
      this.error.set(this.messageOf(err) ?? 'The results could not be downloaded.');
    }
  }

  progressOf(batch: BatchObject): string {
    const counts = batch.request_counts;
    if (!counts || !counts.total) return '—';
    const done = counts.completed + counts.failed;
    return `${done} / ${counts.total}${counts.failed ? ` (${counts.failed} failed)` : ''}`;
  }

  isTerminal(batch: BatchObject): boolean {
    return TERMINAL.has(batch.status);
  }

  private messageOf(err: unknown): string | null {
    const body = (err as { error?: { error?: { message?: string }; detail?: string } })?.error;
    return body?.error?.message ?? body?.detail ?? null;
  }
}
