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
    vi.spyOn(window, 'confirm').mockReturnValue(true);
    const pending = deferred<unknown>();
    service.startBenchmark.mockReturnValue(pending.promise);
    const first = component.startBenchmark(pair);
    await component.startBenchmark(pair);
    expect(service.startBenchmark).toHaveBeenCalledTimes(1);
    pending.resolve({});
    await first;
    expect(component.benchmarkStartingPairId()).toBeNull();
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
});
