import { TestBed } from '@angular/core/testing';
import { BenchmarkResults } from './benchmark-results';
import { ModelProviderBenchmark } from '../../shared/models/provider.model';
import { benchmarkProgress } from './benchmark-progress';

function run(id: number, rate: number, baseline?: number, pair = 1): ModelProviderBenchmark {
  return { id, model_provider_id: pair, model_id: 1, model_name: 'Model', provider_id: pair,
    provider_name: 'Worker', dataset: 'openai/gsm8k', sample_size: 50, recorded_at: '2026-10-21T04:00:00Z',
    configuration: baseline ? { nightly: { baseline_id: baseline, parameters: { max_num_seqs: 8 }, original: { max_num_seqs: 4 } } } : {},
    metrics: { request_totals: { successful: 50, total: 50, errored: 0, incomplete: 0 },
      output_tokens_per_second: { successful: { mean: rate, percentiles: { p50: rate, p95: rate, p99: rate } } } } };
}

describe('Benchmark result baseline', () => {
  it('starts collapsed and preserves the selected order when reopened', () => {
    const fixture = TestBed.createComponent(BenchmarkResults);
    fixture.componentRef.setInput('runs', [run(1, 50), run(2, 40)]);
    fixture.detectChanges();
    const history = fixture.nativeElement.querySelector('.run-history') as HTMLDetailsElement;
    const toggle = history.querySelector('summary')!;
    expect(history.open).toBe(false);
    toggle.click();
    expect(history.open).toBe(true);
    (history.querySelectorAll('.sortable button')[1] as HTMLButtonElement).click();
    fixture.detectChanges();
    expect(history.querySelectorAll('th')[4].getAttribute('aria-sort')).toBe('descending');
    expect(fixture.componentInstance.visibleRows().map(row => row.run.id)).toEqual([1, 2]);
    toggle.click();
    expect(history.open).toBe(false);
    toggle.click();
    expect(history.open).toBe(true);
    expect(fixture.componentInstance.visibleRows().map(row => row.run.id)).toEqual([1, 2]);
  });

  it('sorts all measurements before limiting the list, with invalid values last in both directions', () => {
    const fixture = TestBed.createComponent(BenchmarkResults);
    fixture.componentRef.setInput('runs', [run(1, 100), run(2, 0), run(3, 20), run(4, 20),
      run(5, 50), run(6, NaN), run(7, Infinity)]);
    const component = fixture.componentInstance;
    component.sortBy('after');
    expect(component.visibleRows().map(row => row.run.id)).toEqual([1, 5, 4, 3, 2]);
    component.showAll.set(true);
    expect(component.visibleRows().map(row => row.run.id)).toEqual([1, 5, 4, 3, 2, 7, 6]);
    component.sortBy('after');
    expect(component.visibleRows().map(row => row.run.id)).toEqual([2, 4, 3, 5, 1, 7, 6]);
  });

  it('sorts baseline values and percentage gains numerically, including losses and missing baselines', () => {
    const fixture = TestBed.createComponent(BenchmarkResults);
    fixture.componentRef.setInput('runs', [run(1, 40, 1), run(2, 20, 1), run(3, 40, 1),
      run(4, 80, 1), run(5, 100, 5), run(6, 110, 5), run(7, 50, 999)]);
    const component = fixture.componentInstance;
    component.showAll.set(true);
    component.sortBy('delta');
    expect(component.visibleRows().map(row => row.run.id)).toEqual([4, 6, 3, 2, 7, 5, 1]);
    component.sortBy('delta');
    expect(component.visibleRows().map(row => row.run.id)).toEqual([2, 3, 6, 4, 7, 5, 1]);
    component.sortBy('before');
    expect(component.visibleRows().map(row => row.run.id)).toEqual([6, 4, 3, 2, 7, 5, 1]);
    component.sortBy('before');
    expect(component.visibleRows().map(row => row.run.id)).toEqual([4, 3, 2, 6, 7, 5, 1]);
  });

  it('keeps older runs available without expanding the initial result list', () => {
    const fixture = TestBed.createComponent(BenchmarkResults);
    fixture.componentRef.setInput('runs', Array.from({ length: 7 }, (_, i) => run(i + 1, 40)));
    fixture.detectChanges();
    expect(fixture.nativeElement.querySelectorAll('tbody tr')).toHaveLength(5);
    fixture.nativeElement.querySelector('.results-more').click();
    fixture.detectChanges();
    expect(fixture.nativeElement.querySelectorAll('tbody tr')).toHaveLength(7);
  });

  it('compares only the explicitly linked baseline on the same deployment', () => {
    const fixture = TestBed.createComponent(BenchmarkResults);
    fixture.componentRef.setInput('runs', [run(1, 40, 1), run(2, 50, 1), run(3, 60), run(4, 80, 1, 2)]);
    const rows = fixture.componentInstance.rows();
    expect(rows.find(row => row.run.id === 2)?.delta).toBe(25);
    expect(rows.find(row => row.run.id === 1)?.before).toBeNull();
    expect(rows.find(row => row.run.id === 3)?.before).toBeNull();
    expect(rows.find(row => row.run.id === 4)?.before).toBeNull();
  });

  it('shows requested manual changes without inventing a throughput baseline', () => {
    const fixture = TestBed.createComponent(BenchmarkResults);
    const manual = run(5, 40);
    manual.configuration = { requested_overrides: { max_num_seqs: 8 } };
    fixture.componentRef.setInput('runs', [manual]);
    expect(fixture.componentInstance.rows()[0].changes).toEqual(['Sequences → 8']);
    expect(fixture.componentInstance.rows()[0].before).toBeNull();
  });

  it('leaves a deleted baseline and historical measurement times unknown', () => {
    const fixture = TestBed.createComponent(BenchmarkResults);
    fixture.componentRef.setInput('runs', [run(2, 50, 1)]);
    expect(fixture.componentInstance.rows()[0].before).toBeNull();
    expect(fixture.componentInstance.rows()[0].measurement).toBeUndefined();
  });
});

function measured(id: number, rate: number, baseline: number, day: number, concurrency = 4): ModelProviderBenchmark {
  const result = run(id, rate, baseline);
  result.configuration = { ...result.configuration,
    serving: { tensor_parallel_size: 1, pipeline_parallel_size: 1, max_num_seqs: id === baseline ? 4 : 8 },
    measurement: { ended_at: `2026-10-${day}T05:10:00Z` },
    scenario: { spec: { data: [{ load_kwargs: { name: 'main', split: 'test' } }], seed: { value: 42 },
      data_column_mapper: { column_mappings: { text_column: 'question' } },
      backend: { extras: { body: { max_tokens: 512 } } } } },
    benchmark: { profile: { kind: 'concurrent' }, strategy: { max_concurrency: concurrency } },
  };
  return result;
}

describe('Nightly progress', () => {
  it('orders completed nights and keeps the best measured variant, including regressions', () => {
    const groups = benchmarkProgress([measured(3, 40, 3, 22), measured(4, 44, 3, 22), measured(5, 42, 3, 22),
      measured(1, 40, 1, 21), measured(2, 38, 1, 21)]);
    expect(groups).toHaveLength(1);
    expect(groups[0].points.map(point => point.run.id)).toEqual([2, 4]);
    expect(groups[0].points[0].gain).toBeCloseTo(-5);
    expect(groups[0].points[1].gain).toBeCloseTo(10);
    expect(groups[0].min).toBeLessThan(-5);
    expect(groups[0].max).toBeGreaterThan(10);
  });

  it('separates workloads and rejects changes to input generation within a comparison', () => {
    const changed = measured(7, 99, 1, 22);
    (changed.configuration['scenario'] as { spec: { seed: { value: number } } }).spec.seed.value = 99;
    const missing = measured(8, 99, 999, 22);
    const failed = measured(9, 99, 1, 22);
    failed.metrics.request_totals.errored = 1;
    const groups = benchmarkProgress([measured(1, 40, 1, 21), measured(2, 44, 1, 21),
      measured(3, 40, 3, 22, 8), measured(4, 48, 3, 22, 8), changed, missing, failed, run(10, 99, 1)]);
    expect(groups).toHaveLength(2);
    expect(groups.map(group => group.points.map(point => point.run.id))).toEqual([[4], [2]]);
    expect(groups.every(group => !group.line.includes('NaN'))).toBe(true);
  });

  it('renders one measurement without inventing a time series and removes deleted comparisons', () => {
    const fixture = TestBed.createComponent(BenchmarkResults);
    fixture.componentRef.setInput('runs', [measured(1, 40, 1, 21), measured(2, 44, 1, 21)]);
    fixture.detectChanges();
    expect(fixture.nativeElement.querySelectorAll('.progress-point')).toHaveLength(1);
    expect(fixture.nativeElement.querySelector('polyline')).toBeNull();
    fixture.componentRef.setInput('runs', [measured(2, 44, 1, 21)]);
    fixture.detectChanges();
    expect(fixture.nativeElement.querySelector('.benchmark-progress')).toBeNull();
  });
});


describe('Top measured configuration', () => {
  it('keeps independent provider records and rejects partial or invalid measurements', () => {
    const fixture = TestBed.createComponent(BenchmarkResults);
    const partial = run(4, 999);
    partial.metrics.request_totals.successful = 49;
    const failed = run(5, 1000);
    failed.metrics.request_totals.errored = 1;
    fixture.componentRef.setInput('runs', [run(1, 40), run(2, 50), run(3, 30, undefined, 2), partial, failed, run(6, NaN)]);
    expect(fixture.componentInstance.topRuns().map(top => top.run.id)).toEqual([2, 3]);
  });

  it('shows the winning saved parameters and recalculates after removal', () => {
    const fixture = TestBed.createComponent(BenchmarkResults);
    const winner = run(2, 50);
    winner.configuration = { serving: { max_num_seqs: 20, enable_prefix_caching: false } };
    fixture.componentRef.setInput('runs', [run(1, 40), winner]);
    expect(fixture.componentInstance.topRuns()[0].parameters.find(item => item.key === 'max_num_seqs')?.value).toBe('20');
    expect(fixture.componentInstance.topRuns()[0].parameters.find(item => item.key === 'enable_prefix_caching')?.value).toBe('Disabled');
    fixture.componentRef.setInput('runs', [run(1, 40)]);
    expect(fixture.componentInstance.topRuns()[0].run.id).toBe(1);
  });
});
