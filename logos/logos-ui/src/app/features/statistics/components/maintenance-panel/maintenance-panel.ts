import {
  ChangeDetectionStrategy,
  Component,
  Input,
  OnChanges,
  SimpleChanges,
  computed,
  inject,
  signal,
} from '@angular/core';
import { CommonModule } from '@angular/common';
import {
  MaintenanceBenchmark,
  MaintenanceCalibration,
  MaintenanceRecovery,
  MaintenanceStatus,
  StatisticsService,
} from '../../services/statistics.service';
import { ModelManagementService } from '../../../../core/services/model-management.service';
import { ModalConfirmComponent } from '../../../../shared/components/modal/modal-confirm/modal-confirm';
import { formatTimeAgo } from '../../statistics.utils';
import { messageIn } from '../lane-health-panel/lane-health-panel';

export type MaintenanceHolderKind = 'calibration' | 'benchmark' | 'recovery';

/** One entry of the maintenance status: something that holds the slot, and what can be done about it. */
export interface MaintenanceHolderRow {
  key: string;
  kind: MaintenanceHolderKind;
  label: string;
  provider: string;
  details: string[];
  warning: string | null;
  since: string | null;
  providerId: number | null;
  claimToken: string | null;
  jobId: number | null;
  /** The nightly deployment a recovery belongs to. */
  modelProviderId: number | null;
  canStop: boolean;
  canCancel: boolean;
  canReleaseRecovery: boolean;
  /** Offered without a failed stop first: the provider cannot confirm a stop at all. */
  releaseOffered: boolean;
}

function providerLabel(name: string | null, id: number | null): string {
  return name || (id != null ? `Provider ${id}` : 'Unknown provider');
}

export function calibrationRow(c: MaintenanceCalibration): MaintenanceHolderRow {
  const details: string[] = [];
  if (c.automatic === true) details.push('Nightly calibration');
  else if (c.automatic === false) details.push('Started by an administrator');
  else details.push('Running without a claim');
  let warning: string | null = null;
  if (!c.online) {
    warning = 'The provider is offline, so it cannot confirm that calibration ended.';
  } else if (!c.status_supported) {
    warning = 'The provider cannot report its calibration status. Update its worker software.';
  } else if (c.claim_token && c.confirmed === false) {
    details.push('Start not confirmed yet');
  } else if (c.claim_token && !c.calibrating) {
    details.push('Waiting for the provider to confirm the end');
  }
  return {
    key: c.claim_token ? `calibration:${c.claim_token}` : `calibration:live:${c.provider_id}`,
    kind: 'calibration',
    label: 'Calibrating',
    provider: providerLabel(c.provider_name, c.provider_id),
    details,
    warning,
    since: c.since,
    providerId: c.provider_id,
    claimToken: c.claim_token,
    jobId: null,
    modelProviderId: null,
    canStop: c.online,
    canCancel: false,
    canReleaseRecovery: false,
    releaseOffered: !!c.claim_token && (!c.online || !c.status_supported),
  };
}

export function benchmarkRow(b: MaintenanceBenchmark): MaintenanceHolderRow {
  const active = b.status === 'pending' || b.status === 'running';
  const details: string[] = [];
  if (b.model_name) details.push(b.model_name);
  details.push(active ? (b.status === 'pending' ? 'Queued' : 'Running') : 'Cleaning up');
  return {
    key: `benchmark:${b.job_id}`,
    kind: 'benchmark',
    label: b.nightly ? 'Nightly benchmark' : 'Benchmarking',
    provider: providerLabel(b.provider_name, b.provider_id),
    details,
    warning: null,
    since: b.since,
    providerId: b.provider_id,
    claimToken: null,
    jobId: b.job_id,
    modelProviderId: null,
    canStop: false,
    canCancel: active,
    canReleaseRecovery: false,
    releaseOffered: false,
  };
}

export function recoveryRow(r: MaintenanceRecovery): MaintenanceHolderRow {
  const details: string[] = [];
  if (r.model_name) details.push(r.model_name);
  details.push(`Status: ${r.status}`);
  details.push('Puts the original settings back on its own');
  return {
    key: `recovery:${r.model_provider_id}`,
    kind: 'recovery',
    label: 'Nightly recovery',
    provider: providerLabel(r.provider_name, r.provider_id),
    details,
    warning: null,
    since: r.since,
    providerId: r.provider_id,
    claimToken: null,
    jobId: null,
    modelProviderId: r.model_provider_id,
    canStop: false,
    canCancel: false,
    canReleaseRecovery: true,
    releaseOffered: false,
  };
}

export function holderRows(status: MaintenanceStatus | null): MaintenanceHolderRow[] {
  if (!status) return [];
  return [
    ...status.calibrations.map(calibrationRow),
    ...status.benchmarks.map(benchmarkRow),
    ...status.recoveries.map(recoveryRow),
  ];
}

function failureDetail(err: unknown): string {
  const e = err as { status?: number; error?: unknown; message?: string };
  return messageIn(e?.error) ?? (e?.status ? `HTTP ${e.status}` : (e?.message ?? 'unknown error'));
}

/**
 * Who holds the maintenance slot that calibration, benchmarks and nightly
 * recovery share, and the action that frees it. Re-reads the status every
 * time `now` changes, which the statistics page moves on its own refresh
 * cadence.
 */
@Component({
  selector: 'app-stats-maintenance-panel',
  standalone: true,
  imports: [CommonModule, ModalConfirmComponent],
  templateUrl: './maintenance-panel.html',
  changeDetection: ChangeDetectionStrategy.Eager,
  styleUrl: './maintenance-panel.scss',
})
export class MaintenancePanel implements OnChanges {
  @Input() now = Date.now();

  private readonly statisticsService = inject(StatisticsService);
  private readonly modelService = inject(ModelManagementService);

  readonly status = signal<MaintenanceStatus | null>(null);
  readonly loadError = signal<string | null>(null);
  readonly rows = computed(() => holderRows(this.status()));
  /** Key of the row whose action is in flight; one action at a time. */
  readonly busyKey = signal<string | null>(null);
  readonly notice = signal<{ kind: 'success' | 'error'; text: string } | null>(null);
  /** Claims whose stop did not release them: Release is offered from then on. */
  readonly stopFailed = signal<ReadonlySet<string>>(new Set());
  readonly releaseTarget = signal<MaintenanceHolderRow | null>(null);
  readonly releaseError = signal<string | null>(null);
  /** Recoveries whose normal release was refused: Force release is offered from then on. */
  readonly forceOffered = signal<ReadonlySet<string>>(new Set());
  readonly forceTarget = signal<MaintenanceHolderRow | null>(null);
  readonly forceError = signal<string | null>(null);

  readonly formatTimeAgo = formatTimeAgo;

  /** Bumped by every read; only the newest read may set the status. */
  private readSeq = 0;

  ngOnChanges(changes: SimpleChanges): void {
    if (changes['now']) void this.refresh();
  }

  async refresh(): Promise<void> {
    const seq = ++this.readSeq;
    try {
      const status = await this.statisticsService.getMaintenanceStatus();
      if (seq !== this.readSeq) return;
      this.status.set(status);
      this.loadError.set(null);
      // A holder that left the slot takes its offers along; a later holder
      // with the same key starts with the normal action again.
      const live = new Set(this.rows().map((r) => r.key));
      this.forceOffered.update((keys) => new Set([...keys].filter((k) => live.has(k))));
      this.stopFailed.update((keys) => new Set([...keys].filter((k) => live.has(k))));
    } catch (err: unknown) {
      if (seq !== this.readSeq) return;
      this.loadError.set(`Could not read the maintenance status: ${failureDetail(err)}`);
    }
  }

  canRelease(row: MaintenanceHolderRow): boolean {
    return !!row.claimToken && (row.releaseOffered || this.stopFailed().has(row.key));
  }

  async stop(row: MaintenanceHolderRow): Promise<void> {
    if (row.providerId == null || this.busyKey() !== null) return;
    this.busyKey.set(row.key);
    this.notice.set(null);
    try {
      await this.statisticsService.stopCalibration(row.providerId);
      await this.refresh();
      if (row.claimToken && this.rows().some((r) => r.key === row.key)) {
        this.markStopFailed(row.key);
        this.notice.set({
          kind: 'error',
          text: `Calibration on ${row.provider} was asked to stop, but the slot is still held. `
            + 'If the provider cannot confirm the stop, release the claim.',
        });
      } else {
        this.notice.set({ kind: 'success', text: `Calibration on ${row.provider} stopped.` });
      }
    } catch (err: unknown) {
      this.markStopFailed(row.key);
      this.notice.set({ kind: 'error', text: `Stopping calibration on ${row.provider} failed: ${failureDetail(err)}` });
    } finally {
      this.busyKey.set(null);
    }
  }

  async cancel(row: MaintenanceHolderRow): Promise<void> {
    if (row.jobId == null || this.busyKey() !== null) return;
    this.busyKey.set(row.key);
    this.notice.set(null);
    try {
      await this.modelService.cancelBenchmark(row.jobId);
      this.notice.set({ kind: 'success', text: `Benchmark on ${row.provider} cancelled.` });
      await this.refresh();
    } catch (err: unknown) {
      this.notice.set({ kind: 'error', text: `Cancelling the benchmark on ${row.provider} failed: ${failureDetail(err)}` });
    } finally {
      this.busyKey.set(null);
    }
  }

  askRelease(row: MaintenanceHolderRow): void {
    this.releaseError.set(null);
    this.releaseTarget.set(row);
  }

  closeRelease(visible: boolean): void {
    if (!visible && this.busyKey() === null) this.releaseTarget.set(null);
  }

  async confirmRelease(): Promise<void> {
    const row = this.releaseTarget();
    if (!row || row.providerId == null || !row.claimToken || this.busyKey() !== null) return;
    this.busyKey.set(row.key);
    this.releaseError.set(null);
    try {
      const result = await this.statisticsService.releaseCalibrationClaim(row.providerId, row.claimToken);
      this.releaseTarget.set(null);
      this.notice.set({
        kind: 'success',
        text: result.forced
          ? `Claim on ${row.provider} released without confirmation from the provider.`
          : `Calibration on ${row.provider} stopped and its claim released.`,
      });
      await this.refresh();
    } catch (err: unknown) {
      this.releaseError.set(failureDetail(err));
    } finally {
      this.busyKey.set(null);
    }
  }

  /**
   * Release a nightly recovery. The server first checks that the worker runs
   * the original settings; after a refusal the row offers Force release.
   */
  async releaseRecovery(row: MaintenanceHolderRow): Promise<void> {
    if (row.modelProviderId == null || this.busyKey() !== null) return;
    this.busyKey.set(row.key);
    this.notice.set(null);
    try {
      await this.statisticsService.releaseRecovery(row.modelProviderId, false);
      this.notice.set({ kind: 'success', text: `Recovery on ${row.provider} released. It runs its original settings.` });
      await this.refresh();
    } catch (err: unknown) {
      const refused = (err as { status?: number })?.status === 409;
      if (refused) this.markForceOffered(row.key);
      this.notice.set({
        kind: 'error',
        text: `Releasing the recovery on ${row.provider} failed: ${failureDetail(err)}`
          + (refused ? '. If you are sure the settings are right, force the release.' : ''),
      });
      if ((err as { status?: number })?.status === 404) await this.refresh();
    } finally {
      this.busyKey.set(null);
    }
  }

  askForceRelease(row: MaintenanceHolderRow): void {
    this.forceError.set(null);
    this.forceTarget.set(row);
  }

  closeForceRelease(visible: boolean): void {
    if (!visible && this.busyKey() === null) this.forceTarget.set(null);
  }

  async confirmForceRelease(): Promise<void> {
    const row = this.forceTarget();
    if (!row || row.modelProviderId == null || this.busyKey() !== null) return;
    this.busyKey.set(row.key);
    this.forceError.set(null);
    try {
      await this.statisticsService.releaseRecovery(row.modelProviderId, true);
      this.forceTarget.set(null);
      this.notice.set({
        kind: 'success',
        text: `Recovery on ${row.provider} released without checking its settings.`,
      });
      await this.refresh();
    } catch (err: unknown) {
      this.forceError.set(failureDetail(err));
    } finally {
      this.busyKey.set(null);
    }
  }

  private markForceOffered(key: string): void {
    const next = new Set(this.forceOffered());
    next.add(key);
    this.forceOffered.set(next);
  }

  private markStopFailed(key: string): void {
    const next = new Set(this.stopFailed());
    next.add(key);
    this.stopFailed.set(next);
  }
}
