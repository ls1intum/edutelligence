import { ComponentFixture, TestBed } from '@angular/core/testing';
import { ModelProviderBenchmark } from '../../shared/models/provider.model';
import { BenchmarkComparison, comparisonValue } from './benchmark-comparison';
import { canCompare, isolatedRuns } from './benchmark-isolation';

function run(id: number, tp = 1, concurrency = 4, overrides: Partial<ModelProviderBenchmark> = {}): ModelProviderBenchmark {
  const distribution = (mean: number) => ({ successful: { mean, percentiles: { p50: 1, p95: 2, p99: 3 } } });
  return {
    id, model_provider_id: 1, model_id: 1, model_name: 'Qwen', provider_id: 1, provider_name: 'Worker A',
    dataset: 'openai/gsm8k', sample_size: 50, recorded_at: new Date(Date.UTC(2026, 8, 14, 12, id)).toISOString(),
    configuration: {
      metadata: { guidellm_version: '0.7.2' },
      scenario: { spec: {
        data: [{ source: 'openai/gsm8k', load_kwargs: { name: 'main', split: 'test' } }],
        data_column_mapper: { column_mappings: { text_column: 'question' } }, seed: { value: 42 },
        data_loader: { samples: 50, shuffle: false },
        backend: { stream: true, extras: { body: { max_tokens: 512 } } },
      } },
      benchmark: { profile: { kind: concurrency === 1 ? 'synchronous' : 'concurrent' },
        strategy: { max_concurrency: concurrency, worker_count: concurrency } },
      serving: { tensor_parallel_size: tp, pipeline_parallel_size: 1, kv_cache_memory: '4G', enable_prefix_caching: true },
    },
    metrics: {
      request_totals: { successful: 50, errored: 0, incomplete: 0, total: 50 },
      time_to_first_token_ms: distribution(680), request_latency: distribution(7.6),
      output_tokens_per_second: distribution(42),
    }, ...overrides,
  };
}

// The baseline is #1 (TP 1, concurrency 4); #4 changes both parameters.
const runs = () => [run(1), run(2, 2, 4), run(3, 1, 16), run(4, 2, 16), run(5, 1, 1)];

describe('Benchmark parameter isolation', () => {
  it('varies only TP in the TP chart and only concurrency in the concurrency chart', () => {
    expect(isolatedRuns(runs(), run(1), 'tensor_parallel_size').map(run => run.id)).toEqual([1, 2]);
    expect(isolatedRuns(runs(), run(1), 'max_concurrency').map(run => run.id)).toEqual([5, 1, 3]);
  });

  it.each(['dataset', 'sample_size', 'model_provider_id', 'model_id'])('excludes a different %s', key => {
    const changed = run(2, 2, 4, { [key]: key === 'dataset' ? 'org/other' : 20 });
    expect(isolatedRuns([changed], run(1), 'tensor_parallel_size')).toEqual([]);
  });

  it.each([
    ['scenario', 'spec', 'seed', 'value'],
    ['scenario', 'spec', 'backend', 'extras', 'body', 'max_tokens'],
    ['scenario', 'spec', 'data_loader', 'shuffle'],
    ['scenario', 'spec', 'data', 0, 'load_kwargs', 'split'],
    ['scenario', 'spec', 'data', 0, 'load_kwargs', 'revision'],
    ['scenario', 'spec', 'data_column_mapper', 'column_mappings', 'text_column'],
    ['serving', 'pipeline_parallel_size'],
    ['serving', 'kv_cache_memory'],
    ['serving', 'enable_prefix_caching'],
    ['metadata', 'guidellm_version'],
  ])('excludes changed control %j', (...path) => {
    const changed = run(2, 2, 4);
    let target: any = changed.configuration;
    for (const key of path.slice(0, -1)) target = target[key];
    target[path.at(-1)!] = 'different';
    expect(isolatedRuns([changed], run(1), 'tensor_parallel_size')).toEqual([]);
  });

  it('compares request body options, ignoring object key order and job-specific transport details', () => {
    const baseline = run(1);
    const other = run(2, 2, 4);
    const spec = (other.configuration['scenario'] as any).spec;
    spec.backend.target = '/new-job';
    spec.backend.extras.headers = { job: 'different' };
    spec.outputs = [{ path: 'new-report.json' }];
    spec.data[0].load_kwargs = { split: 'test', name: 'main' };
    expect(isolatedRuns([other], baseline, 'tensor_parallel_size')).toHaveLength(1);
    spec.backend.extras.body.temperature = 1;
    expect(isolatedRuns([other], baseline, 'tensor_parallel_size')).toEqual([]);
  });

  it('does not infer missing TP, PP, dataset or concurrency settings for old reports', () => {
    expect(canCompare(run(1, 1, 4, { configuration: {} }))).toBe(false);
    const missing = run(2);
    delete (missing.configuration['serving'] as any).pipeline_parallel_size;
    expect(canCompare(missing)).toBe(false);
    expect(isolatedRuns(runs(), missing, 'max_concurrency')).toEqual([]);
  });

  it('excludes failed or incomplete runs and preserves repeated runs separately', () => {
    const failed = run(8);
    failed.metrics.request_totals = { successful: 49, total: 50, errored: 1, incomplete: 0 };
    expect(canCompare(failed)).toBe(false);
    expect(isolatedRuns([...runs(), run(6), run(7), failed], run(1), 'tensor_parallel_size')
      .map(run => run.id)).toEqual([1, 6, 7, 2]);
  });
});

describe('Benchmark comparison', () => {
  let fixture: ComponentFixture<BenchmarkComparison>;
  beforeEach(() => {
    TestBed.configureTestingModule({ imports: [BenchmarkComparison] });
    fixture = TestBed.createComponent(BenchmarkComparison);
    fixture.componentRef.setInput('runs', runs());
    fixture.detectChanges();
  });
  afterEach(() => TestBed.resetTestingModule());

  it('uses means, converts TTFT from milliseconds, and preserves the aggregate token rate', () => {
    expect(comparisonValue(run(1), 'ttft')).toBe(0.68);
    expect(comparisonValue(run(1), 'ttlt')).toBe(7.6);
    expect(comparisonValue(run(1), 'throughput')).toBe(42);
  });
  it('does not replace missing means with percentiles or zero', () => {
    const benchmark = run(1);
    delete benchmark.metrics.time_to_first_token_ms!.successful.mean;
    expect(comparisonValue(benchmark, 'ttft')).toBeNull();
    expect(fixture.componentInstance.format(null)).toBe('—');
  });
  it.each([NaN, Infinity, -1])('rejects invalid measurements (%s)', value => {
    const benchmark = run(1);
    benchmark.metrics.output_tokens_per_second!.successful.mean = value;
    expect(comparisonValue(benchmark, 'throughput')).toBeNull();
  });
  it('keeps measured zero but rejects runs with no successful requests', () => {
    const benchmark = run(1);
    benchmark.metrics.request_latency!.successful.mean = 0;
    expect(comparisonValue(benchmark, 'ttlt')).toBe(0);
    benchmark.metrics.request_totals.successful = 0;
    expect(comparisonValue(benchmark, 'ttlt')).toBeNull();
  });

  it('defaults to TP 1/concurrency 4 and changes both vertical charts through one metric selector', async () => {
    expect(fixture.componentInstance.baseline()?.id).toBe(1);
    expect(fixture.nativeElement.querySelector('.baseline-picker select').value).toBe('1');
    expect(fixture.nativeElement.querySelectorAll('figure')).toHaveLength(2);
    const select: HTMLSelectElement = fixture.nativeElement.querySelector('.metric-picker select');
    select.value = 'ttft'; select.dispatchEvent(new Event('change'));
    await fixture.whenStable();
    const charts = fixture.componentInstance.charts();
    expect(charts[0].groups.map(group => group.parameter)).toEqual([1, 2]);
    expect(charts[1].groups.map(group => group.parameter)).toEqual([1, 4, 16]);
    expect(charts.flatMap(chart => chart.groups).flatMap(group => group.rows).every(row => row.value === 0.68)).toBe(true);
    expect(fixture.nativeElement.querySelector('.chart-bar').style.height).not.toBe('');
    expect(fixture.nativeElement.querySelectorAll('tbody tr')).toHaveLength(4);
    expect(fixture.nativeElement.querySelectorAll('tbody .active-metric')).toHaveLength(4);
    expect(fixture.nativeElement.querySelector('tbody').textContent).toContain('7.6');
  });

  it('changes fixed controls when a different reference run is selected', async () => {
    const select: HTMLSelectElement = fixture.nativeElement.querySelector('.baseline-picker select');
    select.value = '4'; select.dispatchEvent(new Event('change'));
    await fixture.whenStable();
    expect(fixture.componentInstance.charts().map(chart => chart.fixed)).toEqual(['Concurrency fixed at 16', 'TP fixed at 2']);
    expect(fixture.componentInstance.selected().map(run => run.id).sort()).toEqual([2, 3, 4]);
  });

  it('retains the reference during refresh and falls back if it is deleted', () => {
    const component = fixture.componentInstance;
    component.baselineId.set(4);
    fixture.componentRef.setInput('runs', [...runs(), run(6)]);
    fixture.detectChanges();
    expect(component.baseline()?.id).toBe(4);
    fixture.componentRef.setInput('runs', [run(1)]);
    fixture.detectChanges();
    expect(component.baseline()?.id).toBe(1);
    expect(fixture.nativeElement.querySelectorAll('.comparison-note')).toHaveLength(2);
  });

  it('handles empty and legacy data without invented comparisons', () => {
    fixture.componentRef.setInput('runs', [run(1, 1, 4, { configuration: {} })]);
    fixture.detectChanges();
    expect(fixture.nativeElement.querySelector('figure')).toBeNull();
    expect(fixture.nativeElement.querySelector('.empty').textContent).toContain('No comparable runs');
    fixture.componentRef.setInput('runs', []);
    fixture.detectChanges();
    expect(fixture.componentInstance.baseline()).toBeNull();
  });

  it('uses a common zero-based finite scale and shows missing values explicitly', () => {
    const component = fixture.componentInstance;
    expect(component.chartMax()).toBeGreaterThanOrEqual(42);
    fixture.componentRef.setInput('runs', [run(1, 1, 4, { metrics: { ...run(1).metrics, output_tokens_per_second: undefined } })]);
    fixture.detectChanges();
    expect(component.chartMax()).toBe(1);
    expect(fixture.nativeElement.querySelector('.chart-bar').style.height).toBe('0%');
    expect(fixture.nativeElement.querySelector('.chart-bar').textContent).toContain('—');
  });
});
