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
  /** Settlers of every call, in order — settleCalibrate is the newest one. */
  let calibrateSettlers: Array<() => void>;

  beforeEach(async () => {
    calibrateResult = {};
    settleCalibrate = null;
    calibrateSettlers = [];
    await TestBed.configureTestingModule({
      imports: [WorkerGpuPanel],
      providers: [
        {
          provide: StatisticsService,
          useValue: {
            calibrateUncalibrated: () =>
              new Promise((resolve, reject) => {
                const settle = () =>
                  calibrateResult.error ? reject(calibrateResult.error) : resolve(calibrateResult.body);
                calibrateSettlers.push(settle);
                settleCalibrate = settle;
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

  it('drops a stale answer when the fallback worker changes under a null selection', async () => {
    // No explicit selection: the panel shows providers[0]. The calibrate
    // call goes out to that worker; while it is in flight the worker leaves
    // the sample list, so the fallback flips to the next worker — without
    // activeProvider ever changing. The answer must not land under the new
    // panel.
    panel.activeProvider = null;
    panel.ngOnChanges({ activeProvider: new SimpleChange('w-a', null, true) });
    expect(panel.resolvedActiveProvider).toBe('w-a');

    const pending = panel.handleCalibrateUncalibrated();
    expect(panel.calibrateState().kind).toBe('loading');

    const previous = panel.providerLatestSamples;
    panel.providerLatestSamples = { 'w-b': null };
    panel.ngOnChanges({
      providerLatestSamples: new SimpleChange(previous, panel.providerLatestSamples, true),
    });
    expect(panel.resolvedActiveProvider).toBe('w-b');
    expect(panel.calibrateState().kind).toBe('idle'); // the flip already dropped the state

    calibrateResult.body = { count: 1, models: ['org/a'] };
    settleCalibrate?.();
    await pending;

    // The answer belongs to w-a; w-b's panel stays idle.
    expect(panel.calibrateState().kind).toBe('idle');
  });

  it('drops a stale answer from an earlier calibration of the same worker', async () => {
    // A → B → A: two calibrations of worker A with a switch in between. The
    // provider guard cannot tell the attempts apart — both captured A — so
    // only the per-attempt token keeps the first answer from replacing the
    // second request's loading state.
    const first = panel.handleCalibrateUncalibrated();
    expect(panel.calibrateState().kind).toBe('loading');

    switchTo('w-b');
    expect(panel.calibrateState().kind).toBe('idle');
    switchTo('w-a');
    expect(panel.calibrateState().kind).toBe('idle');

    const second = panel.handleCalibrateUncalibrated();
    expect(panel.calibrateState().kind).toBe('loading');
    expect(calibrateSettlers).toHaveLength(2);

    // The first (stale) answer lands first — it belongs to the earlier
    // attempt and must not touch the newer one's state.
    calibrateResult.body = { count: 1, models: ['org/a'] };
    calibrateSettlers[0]();
    await first;

    expect(panel.calibrateState().kind).toBe('loading');

    // The second answer resolves it.
    calibrateResult.body = { count: 2, models: ['org/a', 'org/b'] };
    settleCalibrate?.();
    await second;

    expect(panel.calibrateState()).toEqual({
      kind: 'success',
      message: 'Calibrating 2 model(s): org/a, org/b',
    });
  });
});

/**
 * The "Stop calibration" button reuses calibrate's staleness-guard pattern
 * (generation counter + provider check) — these tests exercise the same
 * mechanics for stopState, not every scenario calibrateState already covers.
 */
describe('WorkerGpuPanel stop calibration', () => {
  let fixture: ComponentFixture<WorkerGpuPanel>;
  let panel: WorkerGpuPanel;
  let stopResult: { body?: unknown; error?: unknown };
  let settleStop: (() => void) | null;

  beforeEach(async () => {
    stopResult = {};
    settleStop = null;
    await TestBed.configureTestingModule({
      imports: [WorkerGpuPanel],
      providers: [
        {
          provide: StatisticsService,
          useValue: {
            stopCalibration: () =>
              new Promise((resolve, reject) => {
                settleStop = () => (stopResult.error ? reject(stopResult.error) : resolve(stopResult.body));
              }),
          },
        },
      ],
    }).compileComponents();
    fixture = TestBed.createComponent(WorkerGpuPanel);
    panel = fixture.componentInstance;
    fixture.componentRef.setInput('providerLatestSamples', { 'w-a': null, 'w-b': null });
    fixture.componentRef.setInput('providerDevices', {});
    fixture.componentRef.setInput('providerMeta', {
      'w-a': { provider_id: 1, calibrating: true },
      'w-b': { provider_id: 2, calibrating: false },
    });
    fixture.componentRef.setInput('lanesByProvider', {});
    fixture.componentRef.setInput('activeProvider', 'w-a');
    fixture.detectChanges();
  });

  function switchTo(provider: string): void {
    const previous = panel.activeProvider;
    panel.activeProvider = provider;
    panel.ngOnChanges({ activeProvider: new SimpleChange(previous, provider, true) });
  }

  it('only offers the button while providerMeta reports calibrating', () => {
    expect(panel.canStop).toBe(true);
    switchTo('w-b');
    expect(panel.canStop).toBe(false);
  });

  it('does not offer the button once the calibrating worker goes offline', () => {
    expect(panel.canStop).toBe(true);
    fixture.componentRef.setInput('providerMeta', {
      'w-a': { provider_id: 1, calibrating: true, connection_state: 'offline' },
      'w-b': { provider_id: 2, calibrating: false },
    });
    fixture.detectChanges();
    expect(panel.canStop).toBe(false);
  });

  it('shows the cancelled message for the worker it stopped', async () => {
    const pending = panel.handleStopCalibration();
    expect(panel.stopState().kind).toBe('loading');

    stopResult.body = { was_active: true, current_model: 'org/a' };
    settleStop?.();
    await pending;

    expect(panel.stopState()).toEqual({
      kind: 'success',
      message: 'Calibration cancelled (was calibrating org/a).',
    });
  });

  it('shows a generic cancelled message when current_model is absent', async () => {
    const pending = panel.handleStopCalibration();
    stopResult.body = { was_active: true };
    settleStop?.();
    await pending;

    expect(panel.stopState()).toEqual({
      kind: 'success',
      message: 'Calibration cancelled.',
    });
  });

  it('reports when nothing was running', async () => {
    const pending = panel.handleStopCalibration();
    stopResult.body = { was_active: false };
    settleStop?.();
    await pending;

    expect(panel.stopState()).toEqual({
      kind: 'success',
      message: 'No calibration session was running.',
    });
  });

  it('shows an error for a failed stop call', async () => {
    const pending = panel.handleStopCalibration();
    stopResult.error = { status: 500, error: { error: 'boom' } };
    settleStop?.();
    await pending;

    expect(panel.stopState()).toEqual({ kind: 'error', message: 'boom' });
  });

  it('drops a stale answer when the operator switches worker mid-flight', async () => {
    const pending = panel.handleStopCalibration();
    switchTo('w-b');
    expect(panel.stopState().kind).toBe('idle');

    stopResult.body = { was_active: true, current_model: 'org/a' };
    settleStop?.();
    await pending;

    expect(panel.stopState().kind).toBe('idle');
  });
});

/**
 * Worker-uptime and ws-uptime chips: worker_started_at and
 * connected_at are two independent clocks — a bridge reconnect resets the
 * latter without restarting the worker process, so the labels must track
 * their own timestamp rather than collapsing into one "uptime" value.
 */
describe('WorkerGpuPanel uptime labels', () => {
  let fixture: ComponentFixture<WorkerGpuPanel>;
  let panel: WorkerGpuPanel;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [WorkerGpuPanel],
      providers: [{ provide: StatisticsService, useValue: {} }],
    }).compileComponents();
    fixture = TestBed.createComponent(WorkerGpuPanel);
    panel = fixture.componentInstance;
    fixture.componentRef.setInput('providerLatestSamples', { 'w-a': null });
    fixture.componentRef.setInput('providerDevices', {});
    fixture.componentRef.setInput('lanesByProvider', {});
    fixture.componentRef.setInput('activeProvider', 'w-a');
  });

  it('reads null for both labels when the worker predates uptime reporting', () => {
    fixture.componentRef.setInput('providerMeta', { 'w-a': { provider_id: 1 } });
    fixture.componentRef.setInput('nowMs', new Date('2026-09-16T12:00:00Z').getTime());
    fixture.detectChanges();

    expect(panel.workerUptimeLabel).toBeNull();
    expect(panel.wsUptimeLabel).toBeNull();
  });

  it('formats worker uptime and ws uptime from their own independent timestamps', () => {
    fixture.componentRef.setInput('providerMeta', {
      'w-a': {
        provider_id: 1,
        // Worker process has been up a full day; the bridge reconnected 30
        // minutes ago — the two chips must not read the same value.
        worker_started_at: '2026-09-15T12:00:00Z',
        connected_at: '2026-09-16T11:30:00Z',
      },
    });
    fixture.componentRef.setInput('nowMs', new Date('2026-09-16T12:00:00Z').getTime());
    fixture.detectChanges();

    expect(panel.workerUptimeLabel).toBe('1d 0h');
    expect(panel.wsUptimeLabel).toBe('30m');
  });
});
