import { TestBed } from '@angular/core/testing';
import { ActivatedRoute, provideRouter } from '@angular/router';
import { HttpClient, provideHttpClient } from '@angular/common/http';
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
  let service: { getBenchmarks: ReturnType<typeof vi.fn>; getBenchmarkWorkerLimits: ReturnType<typeof vi.fn>; startBenchmark: ReturnType<typeof vi.fn>; cancelBenchmark: ReturnType<typeof vi.fn> };
  const empty: ModelBenchmarkResponse = { benchmarks: [], pairs: [], runs: [] };
  const pair = { model_provider_id: 1, provider_id: 2, endpoint_configured: true } as ModelBenchmarkPair;
  const run = { id: 3, status: 'running', request: { provider_id: 2 }, result: {} } as ModelBenchmarkRun;

  beforeEach(() => {
    service = { getBenchmarks: vi.fn().mockResolvedValue(empty), getBenchmarkWorkerLimits: vi.fn(), startBenchmark: vi.fn(), cancelBenchmark: vi.fn() };
    TestBed.configureTestingModule({ providers: [
      { provide: ActivatedRoute, useValue: {} },
      { provide: HttpClient, useValue: {} },
      { provide: ModelManagementService, useValue: service },
    ] });
    component = TestBed.runInInjectionContext(() => new ModelErrorReport());
    component.modelId.set(1);
  });
  afterEach(() => { component.ngOnDestroy(); vi.restoreAllMocks(); });

  it('defaults to an online worker instead of the first offline provider', async () => {
    const offline = { ...pair, provider_type: 'logosnode', provider_name: 'Offline worker' } as ModelBenchmarkPair;
    const online = { ...offline, model_provider_id: 2, provider_id: 3, provider_name: 'Online worker' };
    service.getBenchmarks.mockResolvedValue({ ...empty, pairs: [offline, online] });
    service.getBenchmarkWorkerLimits.mockImplementation(async (id: number) => {
      if (id === offline.model_provider_id) throw { error: { error: { message: 'Worker is offline. Hardware limits are unavailable.' } } };
      return { gpu_count: 1, current: {} };
    });
    await component.loadPerformance();
    expect(component.selectedBenchmarkPair()).toEqual(online);
    expect(component.benchmarkProviderUnavailable(offline)).toBe(true);
    expect(component.benchmarkProviderLabel(online)).toBe('Online worker · Online');
    await component.startBenchmark(offline);
    expect(service.startBenchmark).not.toHaveBeenCalled();
  });

  it('preserves an explicit provider choice while online status refreshes', async () => {
    const first = { ...pair, provider_type: 'logosnode' } as ModelBenchmarkPair;
    const second = { ...first, model_provider_id: 2, provider_id: 3 };
    component.selectedBenchmarkPairId.set(second.model_provider_id);
    service.getBenchmarks.mockResolvedValue({ ...empty, pairs: [first, second] });
    service.getBenchmarkWorkerLimits.mockResolvedValue({ gpu_count: 1, current: {} });
    await component.loadPerformance();
    expect(component.selectedBenchmarkPair()).toEqual(second);
    await component.loadPerformance(1, true);
    expect(service.getBenchmarkWorkerLimits).toHaveBeenCalledTimes(2);
  });

  it('keeps cloud providers usable when worker status cannot be determined', async () => {
    const worker = { ...pair, provider_type: 'logosnode' } as ModelBenchmarkPair;
    const cloud = { ...pair, model_provider_id: 2, provider_id: 3, provider_type: 'cloud' } as ModelBenchmarkPair;
    service.getBenchmarks.mockResolvedValue({ ...empty, pairs: [worker, cloud] });
    service.getBenchmarkWorkerLimits.mockRejectedValue(new Error('Network error'));
    await component.loadPerformance();
    expect(component.selectedBenchmarkPair()).toEqual(cloud);
    expect(component.benchmarkAvailability().get(worker.model_provider_id)).toBe('unknown');
    expect(component.benchmarkProviderUnavailable(cloud)).toBe(false);
  });

  it('blocks starting when every worker has no GPUs available', async () => {
    const worker = { ...pair, provider_type: 'logosnode' } as ModelBenchmarkPair;
    service.getBenchmarks.mockResolvedValue({ ...empty, pairs: [worker] });
    service.getBenchmarkWorkerLimits.mockResolvedValue({ gpu_count: 0, current: {} });
    await component.loadPerformance();
    component.benchmarkConfirmPairId.set(worker.model_provider_id);
    await component.startBenchmark(worker);
    expect(service.startBenchmark).not.toHaveBeenCalled();
    expect(component.benchmarkConfirmPairId()).toBeNull();
  });

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

  it('closes a stale confirmation when polling finds a competing run', async () => {
    component.benchmarkPairs.set([pair]);
    component.benchmarkConfirmPairId.set(pair.model_provider_id);
    component.benchmarkRuns.set([run]);
    await component.startBenchmark(pair);
    expect(service.startBenchmark).not.toHaveBeenCalled();
    expect(component.benchmarkConfirmPairId()).toBeNull();
    expect(component.benchmarkStartError()).toContain('already running on this provider');
  });

  it('closes a stale confirmation when the provider endpoint becomes unavailable', async () => {
    const unavailable = { ...pair, endpoint_configured: false };
    component.benchmarkPairs.set([unavailable]);
    component.benchmarkConfirmPairId.set(pair.model_provider_id);
    await component.startBenchmark(unavailable);
    expect(service.startBenchmark).not.toHaveBeenCalled();
    expect(component.benchmarkConfirmPairId()).toBeNull();
    expect(component.benchmarkStartError()).toContain('provider or settings changed');
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

describe('Benchmark provider picker', () => {
  it('displays the online selection after asynchronously loaded options arrive', async () => {
    const offline = { model_provider_id: 1, provider_id: 1, provider_name: 'Offline worker',
      provider_type: 'logosnode', endpoint_configured: true } as ModelBenchmarkPair;
    const online = { ...offline, model_provider_id: 2, provider_id: 2, provider_name: 'Online worker' };
    TestBed.configureTestingModule({
      imports: [ModelErrorReport],
      providers: [provideRouter([]), provideHttpClient(), {
        provide: ModelManagementService, useValue: {
          getBenchmarks: async () => ({ benchmarks: [], runs: [], pairs: [offline, online] }),
          getBenchmarkWorkerLimits: async (id: number) => {
            if (id === 1) throw { error: { detail: 'Worker is offline.' } };
            return { gpu_count: 1, current: {} };
          },
          getBenchmarkDatasetMetadata: async () => ({ dataset: 'openai/gsm8k', subset: 'main', split: 'test',
            splits: [{ subset: 'main', split: 'test' }], text_columns: ['question'] }),
        },
      }],
    });
    vi.spyOn(ModelErrorReport.prototype, 'ngOnInit').mockResolvedValue();
    const fixture = TestBed.createComponent(ModelErrorReport);
    const component = fixture.componentInstance;
    component.model.set({ id: 1, name: 'Test model' } as any);
    component.modelId.set(1);
    component.loading.set(false);
    component.activeTab.set('performance');
    component.performanceView.set('run');
    fixture.detectChanges();
    await component.loadPerformance();
    fixture.detectChanges();
    await fixture.whenStable();
    fixture.detectChanges();
    const picker = fixture.nativeElement.querySelector('.benchmark-basics select') as HTMLSelectElement;
    expect(picker.value).toBe('2');
    expect(picker.selectedOptions[0].textContent).toContain('Online worker · Online');
    expect(picker.options[0].disabled).toBe(true);
    fixture.destroy();
    vi.restoreAllMocks();
  });
});
