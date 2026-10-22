import { SimpleChange } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { vi } from 'vitest';
import { MaintenancePanel, benchmarkRow, calibrationRow, holderRows, recoveryRow } from './maintenance-panel';
import {
  MaintenanceCalibration,
  MaintenanceStatus,
  StatisticsService,
} from '../../services/statistics.service';
import { ModelManagementService } from '../../../../core/services/model-management.service';

const SINCE = '2026-10-22T04:00:00Z';

function calibration(overrides: Partial<MaintenanceCalibration> = {}): MaintenanceCalibration {
  return {
    provider_id: 24,
    provider_name: 'Mac1',
    claim_token: 'claim-1',
    automatic: true,
    confirmed: true,
    since: SINCE,
    age_s: 3600,
    online: true,
    calibrating: true,
    status_supported: true,
    ...overrides,
  };
}

function status(overrides: Partial<MaintenanceStatus> = {}): MaintenanceStatus {
  return { limit: 1, free: false, calibrations: [], benchmarks: [], recoveries: [], ...overrides };
}

const FREE = status({ free: true });

describe('maintenance holder rows', () => {
  it('offers only a stop for a running calibration on a reachable provider', () => {
    const row = calibrationRow(calibration());
    expect(row.label).toBe('Calibrating');
    expect(row.details).toEqual(['Nightly calibration']);
    expect(row.canStop).toBe(true);
    expect(row.releaseOffered).toBe(false);
    expect(row.warning).toBeNull();
  });

  it('offers the release for an offline provider, which cannot be stopped', () => {
    const row = calibrationRow(calibration({ online: false }));
    expect(row.canStop).toBe(false);
    expect(row.releaseOffered).toBe(true);
    expect(row.warning).toContain('offline');
  });

  it('offers the release when the provider cannot report its calibration status', () => {
    const row = calibrationRow(calibration({ status_supported: false, automatic: false }));
    expect(row.canStop).toBe(true);
    expect(row.releaseOffered).toBe(true);
    expect(row.details).toEqual(['Started by an administrator']);
    expect(row.warning).toContain('Update its worker software');
  });

  it('never offers a release for a session without a claim', () => {
    const row = calibrationRow(
      calibration({ claim_token: null, automatic: null, confirmed: null, since: null, online: false }),
    );
    expect(row.releaseOffered).toBe(false);
    expect(row.details).toEqual(['Running without a claim']);
    expect(row.key).toBe('calibration:live:24');
  });

  it('says when an idle provider has not confirmed the end yet', () => {
    expect(calibrationRow(calibration({ calibrating: false })).details).toContain(
      'Waiting for the provider to confirm the end',
    );
    expect(calibrationRow(calibration({ confirmed: false })).details).toContain('Start not confirmed yet');
  });

  it('offers a cancel only while the benchmark job is active', () => {
    const running = benchmarkRow({
      job_id: 7, status: 'running', provider_id: 3, provider_name: 'gpu-a',
      model_name: 'Qwen', nightly: false, since: SINCE, age_s: 60,
    });
    expect(running.label).toBe('Benchmarking');
    expect(running.details).toEqual(['Qwen', 'Running']);
    expect(running.canCancel).toBe(true);
    const cleanup = benchmarkRow({
      job_id: 8, status: null, provider_id: 3, provider_name: null,
      model_name: null, nightly: true, since: SINCE, age_s: 60,
    });
    expect(cleanup.label).toBe('Nightly benchmark');
    expect(cleanup.provider).toBe('Provider 3');
    expect(cleanup.details).toEqual(['Cleaning up']);
    expect(cleanup.canCancel).toBe(false);
  });

  it('shows a recovery without an action, since it finishes on its own', () => {
    const row = recoveryRow({
      model_provider_id: 31, status: 'restoring', provider_id: 3, provider_name: 'gpu-a',
      model_name: 'Qwen', since: SINCE, age_s: 5,
    });
    expect(row.label).toBe('Nightly recovery');
    expect(row.canStop || row.canCancel || row.releaseOffered).toBe(false);
  });

  it('lists every holder, calibrations first, when several share the slot', () => {
    const rows = holderRows(
      status({
        limit: 2,
        calibrations: [calibration(), calibration({ provider_id: 25, provider_name: 'gpu-b', claim_token: 'claim-2' })],
        benchmarks: [{
          job_id: 7, status: 'pending', provider_id: 3, provider_name: 'gpu-a',
          model_name: null, nightly: false, since: null, age_s: null,
        }],
      }),
    );
    expect(rows.map((r) => r.key)).toEqual(['calibration:claim-1', 'calibration:claim-2', 'benchmark:7']);
    expect(holderRows(null)).toEqual([]);
  });
});

describe('MaintenancePanel', () => {
  let fixture: ComponentFixture<MaintenancePanel>;
  let component: MaintenancePanel;
  let getMaintenanceStatus: ReturnType<typeof vi.fn>;
  let stopCalibration: ReturnType<typeof vi.fn>;
  let releaseCalibrationClaim: ReturnType<typeof vi.fn>;
  let cancelBenchmark: ReturnType<typeof vi.fn>;

  async function render(initial: MaintenanceStatus): Promise<HTMLElement> {
    getMaintenanceStatus.mockResolvedValue(initial);
    fixture = TestBed.createComponent(MaintenancePanel);
    component = fixture.componentInstance;
    component.ngOnChanges({ now: new SimpleChange(undefined, component.now, true) });
    await fixture.whenStable();
    fixture.detectChanges();
    return fixture.nativeElement as HTMLElement;
  }

  function buttons(root: HTMLElement): string[] {
    return Array.from(root.querySelectorAll('.maintenance__btn')).map((b) => b.textContent!.trim());
  }

  beforeEach(async () => {
    getMaintenanceStatus = vi.fn();
    stopCalibration = vi.fn().mockResolvedValue({ was_active: true });
    releaseCalibrationClaim = vi.fn().mockResolvedValue({ released: true, forced: true });
    cancelBenchmark = vi.fn().mockResolvedValue({ job_id: 7, status: 'failed' });
    await TestBed.configureTestingModule({
      imports: [MaintenancePanel],
      providers: [
        { provide: StatisticsService, useValue: { getMaintenanceStatus, stopCalibration, releaseCalibrationClaim } },
        { provide: ModelManagementService, useValue: { cancelBenchmark } },
      ],
    }).compileComponents();
  });

  it('says that the slot is free when nothing holds it', async () => {
    const root = await render(FREE);
    expect(root.querySelector('.maintenance__badge')!.textContent!.trim()).toBe('Free');
    expect(root.textContent).toContain('The slot is free.');
    expect(buttons(root)).toEqual([]);
  });

  it('mentions the parallel limit when more than one provider may hold the slot', async () => {
    const root = await render(status({ free: true, limit: 2 }));
    expect(root.textContent).toContain('up to 2 providers at a time');
  });

  it('re-reads the status whenever the page clock moves', async () => {
    await render(FREE);
    component.ngOnChanges({ now: new SimpleChange(1, 2, false) });
    await fixture.whenStable();
    expect(getMaintenanceStatus).toHaveBeenCalledTimes(2);
  });

  it('keeps the last status and shows the error when a read fails', async () => {
    const root = await render(status({ calibrations: [calibration()] }));
    getMaintenanceStatus.mockRejectedValue({ status: 503, error: { error: 'Orchestrator down' } });
    await component.refresh();
    fixture.detectChanges();
    expect(root.textContent).toContain('Could not read the maintenance status: Orchestrator down');
    expect(root.textContent).toContain('Mac1');
  });

  it('stops a calibration and reports the freed slot', async () => {
    const root = await render(status({ calibrations: [calibration()] }));
    expect(buttons(root)).toEqual(['Stop calibration']);
    getMaintenanceStatus.mockResolvedValue(FREE);
    await component.stop(component.rows()[0]);
    fixture.detectChanges();
    expect(stopCalibration).toHaveBeenCalledWith(24);
    expect(root.textContent).toContain('Calibration on Mac1 stopped.');
  });

  it('offers the release once a stop leaves the claim in place', async () => {
    const held = status({ calibrations: [calibration()] });
    const root = await render(held);
    getMaintenanceStatus.mockResolvedValue(held);
    await component.stop(component.rows()[0]);
    fixture.detectChanges();
    expect(buttons(root)).toEqual(['Stop calibration', 'Release claim']);
    expect(root.textContent).toContain('release the claim');
  });

  it('offers the release after a failed stop', async () => {
    const root = await render(status({ calibrations: [calibration()] }));
    stopCalibration.mockRejectedValue({ status: 503, error: { error: 'Worker not connected' } });
    await component.stop(component.rows()[0]);
    fixture.detectChanges();
    expect(root.textContent).toContain('Stopping calibration on Mac1 failed: Worker not connected');
    expect(buttons(root)).toContain('Release claim');
  });

  it('releases the claim of an offline provider after confirmation', async () => {
    const root = await render(status({ calibrations: [calibration({ online: false })] }));
    expect(buttons(root)).toEqual(['Release claim']);
    component.askRelease(component.rows()[0]);
    getMaintenanceStatus.mockResolvedValue(FREE);
    await component.confirmRelease();
    fixture.detectChanges();
    expect(releaseCalibrationClaim).toHaveBeenCalledWith(24, 'claim-1');
    expect(component.releaseTarget()).toBeNull();
    expect(root.textContent).toContain('released without confirmation from the provider');
  });

  it('keeps the dialog open with the reason when the release is refused', async () => {
    await render(status({ calibrations: [calibration({ online: false })] }));
    releaseCalibrationClaim.mockRejectedValue({ status: 409, error: { detail: 'The worker still reports a calibration session' } });
    component.askRelease(component.rows()[0]);
    await component.confirmRelease();
    expect(component.releaseTarget()).not.toBeNull();
    expect(component.releaseError()).toBe('The worker still reports a calibration session');
  });

  it('cancels a running benchmark through the benchmark service', async () => {
    const root = await render(
      status({
        benchmarks: [{
          job_id: 7, status: 'running', provider_id: 3, provider_name: 'gpu-a',
          model_name: 'Qwen', nightly: false, since: SINCE, age_s: 60,
        }],
      }),
    );
    expect(buttons(root)).toEqual(['Cancel benchmark']);
    getMaintenanceStatus.mockResolvedValue(FREE);
    await component.cancel(component.rows()[0]);
    fixture.detectChanges();
    expect(cancelBenchmark).toHaveBeenCalledWith(7);
    expect(root.textContent).toContain('Benchmark on gpu-a cancelled.');
  });
});
