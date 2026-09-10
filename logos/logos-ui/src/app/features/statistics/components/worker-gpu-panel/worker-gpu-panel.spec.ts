import { SimpleChange } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { WorkerGpuPanel } from './worker-gpu-panel';
import { StatisticsService } from '../../services/statistics.service';

/**
 * The calibration message under the "Calibrate uncalibrated" button.
 *
 * It is the answer to an action on *one* worker: "Calibrating 2 model(s): …"
 * said on worker A means nothing under worker B's panel. Switching workers
 * must drop it — and an answer that arrives after the switch belongs to the
 * worker it was asked for, so it is discarded rather than shown on the new
 * one.
 */
describe('WorkerGpuPanel calibration message', () => {
  let fixture: ComponentFixture<WorkerGpuPanel>;
  let panel: WorkerGpuPanel;
  let calibrateResult: { body?: unknown; error?: unknown };
  let settleCalibrate: (() => void) | null;

  beforeEach(async () => {
    calibrateResult = {};
    settleCalibrate = null;
    await TestBed.configureTestingModule({
      imports: [WorkerGpuPanel],
      providers: [
        {
          provide: StatisticsService,
          useValue: {
            calibrateUncalibrated: () =>
              new Promise((resolve, reject) => {
                settleCalibrate = () =>
                  calibrateResult.error ? reject(calibrateResult.error) : resolve(calibrateResult.body);
              }),
          },
        },
      ],
    }).compileComponents();
    fixture = TestBed.createComponent(WorkerGpuPanel);
    panel = fixture.componentInstance;
    fixture.componentRef.setInput('providerLatestSamples', { 'w-a': null, 'w-b': null });
    fixture.componentRef.setInput('providerDevices', {});
    fixture.componentRef.setInput('providerMeta', { 'w-a': { provider_id: 1 }, 'w-b': { provider_id: 2 } });
    fixture.componentRef.setInput('lanesByProvider', {});
    fixture.componentRef.setInput('activeProvider', 'w-a');
    fixture.detectChanges();
  });

  /** Move the worker dropdown to another worker, as the framework would. */
  function switchTo(provider: string): void {
    const previous = panel.activeProvider;
    panel.activeProvider = provider;
    panel.ngOnChanges({ activeProvider: new SimpleChange(previous, provider, true) });
  }

  it('shows the success message for the worker it calibrated', async () => {
    const pending = panel.handleCalibrateUncalibrated();
    expect(panel.calibrateState().kind).toBe('loading');

    calibrateResult.body = { count: 2, models: ['org/a', 'org/b'] };
    settleCalibrate?.();
    await pending;

    expect(panel.calibrateState()).toEqual({
      kind: 'success',
      message: 'Calibrating 2 model(s): org/a, org/b',
    });
  });

  it('drops the message when the operator switches to another worker', async () => {
    const pending = panel.handleCalibrateUncalibrated();
    calibrateResult.body = { count: 1, models: ['org/a'] };
    settleCalibrate?.();
    await pending;
    expect(panel.calibrateState().kind).toBe('success');

    switchTo('w-b');
    expect(panel.calibrateState().kind).toBe('idle');
  });

  it('drops an error message on the switch as well', async () => {
    const pending = panel.handleCalibrateUncalibrated();
    calibrateResult.error = { status: 500, error: { error: 'boom' } };
    settleCalibrate?.();
    await pending;
    expect(panel.calibrateState().kind).toBe('error');

    switchTo('w-b');
    expect(panel.calibrateState().kind).toBe('idle');
  });

  it('does not show a stale success answer under the worker the operator moved to', async () => {
    const pending = panel.handleCalibrateUncalibrated();
    // The call is still in flight when the operator switches.
    switchTo('w-b');
    expect(panel.calibrateState().kind).toBe('idle');

    calibrateResult.body = { count: 1, models: ['org/a'] };
    settleCalibrate?.();
    await pending;

    // The answer belongs to w-a; w-b's panel stays idle.
    expect(panel.calibrateState().kind).toBe('idle');
  });

  it('does not show a stale error answer under the worker the operator moved to', async () => {
    const pending = panel.handleCalibrateUncalibrated();
    switchTo('w-b');

    calibrateResult.error = { status: 500, error: { error: 'boom' } };
    settleCalibrate?.();
    await pending;

    expect(panel.calibrateState().kind).toBe('idle');
  });

  it('shows an error for the worker that is still active', async () => {
    const pending = panel.handleCalibrateUncalibrated();
    calibrateResult.error = { status: 500, error: { error: 'boom' } };
    settleCalibrate?.();
    await pending;

    expect(panel.calibrateState()).toEqual({ kind: 'error', message: 'boom' });
  });
});
