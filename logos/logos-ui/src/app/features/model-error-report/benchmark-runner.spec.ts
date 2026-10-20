import { TestBed } from '@angular/core/testing';
import { ActivatedRoute } from '@angular/router';
import { HttpClient } from '@angular/common/http';
import { ModelManagementService } from '../../core/services/model-management.service';
import { ModelBenchmarkPair, ModelBenchmarkRun, ModelBenchmarkResponse } from '../../shared/models/provider.model';
import { ModelErrorReport } from './model-error-report';

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>(r => resolve = r);
  return { promise, resolve };
}

describe('Benchmark runner', () => {
  let component: ModelErrorReport;
  let service: { getBenchmarks: ReturnType<typeof vi.fn>; startBenchmark: ReturnType<typeof vi.fn>; cancelBenchmark: ReturnType<typeof vi.fn> };
  const empty: ModelBenchmarkResponse = { benchmarks: [], pairs: [], runs: [] };
  const pair = { model_provider_id: 1, provider_id: 2, endpoint_configured: true } as ModelBenchmarkPair;
  const run = { id: 3, status: 'running', request: { provider_id: 2 }, result: {} } as ModelBenchmarkRun;

  beforeEach(() => {
    service = { getBenchmarks: vi.fn().mockResolvedValue(empty), startBenchmark: vi.fn(), cancelBenchmark: vi.fn() };
    TestBed.configureTestingModule({ providers: [
      { provide: ActivatedRoute, useValue: {} },
      { provide: HttpClient, useValue: {} },
      { provide: ModelManagementService, useValue: service },
    ] });
    component = TestBed.runInInjectionContext(() => new ModelErrorReport());
    component.modelId.set(1);
  });
  afterEach(() => { component.ngOnDestroy(); vi.restoreAllMocks(); });

  it('does not replace a newer status with a stale polling response', async () => {
    const old = deferred<ModelBenchmarkResponse>();
    service.getBenchmarks.mockReturnValueOnce(old.promise).mockResolvedValueOnce(empty);
    const first = component.loadPerformance();
    await component.loadPerformance(1, true);
    old.resolve({ ...empty, runs: [run] });
    await first;
    expect(component.benchmarkRuns()).toEqual([]);
    expect(component.performanceLoading()).toBe(false);
  });

  it('blocks further starts until the first start finishes', async () => {
    const confirm = vi.spyOn(window, 'confirm');
    const pending = deferred<unknown>();
    service.startBenchmark.mockReturnValue(pending.promise);
    const first = component.startBenchmark(pair);
    await component.startBenchmark(pair);
    expect(service.startBenchmark).toHaveBeenCalledTimes(1);
    expect(confirm).not.toHaveBeenCalled();
    pending.resolve({});
    await first;
    expect(component.benchmarkStartingPairId()).toBeNull();
  });

  it.each([
    ['reconfiguring_worker', 'Applying vLLM settings on hochbruegge · model may restart'],
    ['waiting_for_model', 'Waiting for the model on hochbruegge to become ready'],
  ])('shows the %s preparation phase', (stage, expected) => {
    expect(component.benchmarkStatusLabel({
      ...run,
      request: { ...run.request, provider_name: 'hochbruegge' },
      result: { stage },
    })).toBe(expected);
  });

  it('blocks repeated cancellation while cancellation is pending', async () => {
    const pending = deferred<unknown>();
    service.cancelBenchmark.mockReturnValue(pending.promise);
    const first = component.cancelBenchmark(run);
    await component.cancelBenchmark(run);
    expect(service.cancelBenchmark).toHaveBeenCalledTimes(1);
    pending.resolve({});
    await first;
    expect(component.benchmarkCancellingJobId()).toBeNull();
  });
  it('submits a full batch once and closes the confirmation dialog', async () => {
    const batch = { repetitions: 20, configurations: [{ ...component.benchmarkSettings(), samples: 50 }] };
    component.performanceView.set('run');
    component.benchmarkBatch.set(batch);
    component.benchmarkConfirmPairId.set(1);
    await component.startBenchmark(pair);
    expect(service.startBenchmark).toHaveBeenCalledWith(1, 50, component.benchmarkSettings(), batch);
    expect(component.benchmarkConfirmPairId()).toBeNull();
    expect(component.benchmarkTotalRuns()).toBe(20);
    expect(component.performanceView()).toBe('results');
  });
  it('does not submit an invalid batch', async () => {
    component.benchmarkBatchValid.set(false);
    await component.startBenchmark(pair);
    expect(service.startBenchmark).not.toHaveBeenCalled();
  });

  it('keeps the setup and error visible when starting fails', async () => {
    component.performanceView.set('run');
    component.benchmarkSampleSize.set(1);
    service.startBenchmark.mockRejectedValue(new Error('unavailable'));
    await component.startBenchmark(pair);
    expect(component.performanceView()).toBe('run');
    expect(component.benchmarkSampleSize()).toBe(1);
    expect(component.benchmarkStartError()).toBe('Could not start the benchmark.');
  });

  it('summarizes the actual batch sample sizes instead of the base value', () => {
    component.benchmarkBatch.set({
      repetitions: 2,
      configurations: [1, 10].map(samples => ({ ...component.benchmarkSettings(), samples })),
    });
    expect(component.benchmarkSampleRange()).toBe('1–10');
    expect(component.benchmarkSampleLabel()).toBe('1–10 samples');
    expect(component.benchmarkTotalRuns()).toBe(4);
  });

  it('shows one sample when every batch configuration uses one sample', () => {
    component.benchmarkBatch.set({
      repetitions: 2,
      configurations: [{ ...component.benchmarkSettings(), samples: 1 }],
    });
    expect(component.benchmarkSampleRange()).toBe('1');
    expect(component.benchmarkSampleLabel()).toBe('1 sample');
    component.benchmarkBatch.set(null);
    expect(component.benchmarkSampleLabel()).toBe('50 samples');
  });

});
