import { ComponentFixture, TestBed } from '@angular/core/testing';
import { ModelProviderBenchmark } from '../../shared/models/provider.model';
import { BenchmarkComparison, comparisonValue } from './benchmark-comparison';

function run(id: number, overrides: Partial<ModelProviderBenchmark> = {}): ModelProviderBenchmark {
  const distribution = (mean: number) => ({ successful: { mean, percentiles: { p50: 1, p95: 2, p99: 3 } } });
  return {
    id, model_provider_id: 1, model_id: 1, model_name: 'Qwen', provider_id: 1, provider_name: 'Worker A',
    dataset: 'openai/gsm8k', sample_size: 5, recorded_at: `2026-09-14T12:00:0${id}Z`, configuration: {},
    metrics: {
      request_totals: { successful: 5, errored: 0, incomplete: 0, total: 5 },
      time_to_first_token_ms: distribution(680), request_latency: distribution(7.6),
      output_tokens_per_second: distribution(42),
    }, ...overrides,
  };
}

describe('Benchmark comparison', () => {
  let fixture: ComponentFixture<BenchmarkComparison>;
  beforeEach(() => {
    TestBed.configureTestingModule({ imports: [BenchmarkComparison] });
    fixture = TestBed.createComponent(BenchmarkComparison);
    fixture.componentRef.setInput('runs', [run(1), run(2), run(3)]);
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

  it('keeps a measured zero but rejects runs with no successful requests', () => {
    const benchmark = run(1);
    benchmark.metrics.request_latency!.successful.mean = 0;
    expect(comparisonValue(benchmark, 'ttlt')).toBe(0);
    benchmark.metrics.request_totals.successful = 0;
    expect(comparisonValue(benchmark, 'ttlt')).toBeNull();
  });

  it('defaults to the three newest runs and switches only the chart metric', async () => {
    expect(fixture.componentInstance.selected().map(run => run.id)).toEqual([3, 2, 1]);
    const select: HTMLSelectElement = fixture.nativeElement.querySelector('.metric-picker select');
    select.value = 'ttft'; select.dispatchEvent(new Event('change'));
    await fixture.whenStable();
    expect(fixture.componentInstance.chartRows().map(row => row.value)).toEqual([0.68, 0.68, 0.68]);
    expect(fixture.nativeElement.querySelectorAll('tbody tr')).toHaveLength(3);
    const metricCells = Array.from<HTMLTableCellElement>(fixture.nativeElement.querySelectorAll('tbody tr:first-child td.numeric'));
    expect(metricCells.map(cell => cell.textContent!.trim())).toEqual(['5', '42', '0.68', '7.6']);
    expect(fixture.nativeElement.querySelectorAll('tbody .active-metric')).toHaveLength(3);
  });

  it('limits selection to five without preventing deselection', async () => {
    fixture.componentRef.setInput('runs', [1, 2, 3, 4, 5, 6].map(id => run(id)));
    fixture.detectChanges();
    const component = fixture.componentInstance;
    component.toggleRun(3); component.toggleRun(2); component.toggleRun(1);
    await fixture.whenStable();
    expect(component.selected()).toHaveLength(5);
    const unchecked: HTMLInputElement = fixture.nativeElement.querySelector('input:not(:checked)');
    expect(unchecked.disabled).toBe(true);
    component.toggleRun(6);
    await fixture.whenStable();
    expect(component.selected()).toHaveLength(4);
    expect(Array.from<HTMLInputElement>(fixture.nativeElement.querySelectorAll('input')).every(input => !input.disabled)).toBe(true);
  });

  it('filters available runs without silently removing selections', async () => {
    fixture.componentRef.setInput('runs', [run(1), run(2, { provider_id: 2, provider_name: 'Worker B', dataset: 'org/data' })]);
    const component = fixture.componentInstance;
    component.providerFilter.set('2'); component.datasetFilter.set('org/data');
    await fixture.whenStable();
    expect(component.filteredRuns().map(run => run.id)).toEqual([2]);
    expect(component.selected()).toHaveLength(2);
    expect(component.differentInputs()).toBe(true);
    expect(fixture.nativeElement.querySelector('.comparison-note')).not.toBeNull();
  });

  it('updates measurements and removes deleted runs without selecting unrelated new runs', () => {
    const component = fixture.componentInstance;
    component.toggleRun(2);
    fixture.componentRef.setInput('runs', [run(3, { metrics: { ...run(3).metrics, request_latency: undefined } }), run(4)]);
    fixture.detectChanges();
    expect(component.selected().map(run => run.id)).toEqual([3]);
    expect(component.value(component.selected()[0], 'ttlt')).toBe('—');
  });

  it('supports an empty selection and can select again through the checkbox', async () => {
    const component = fixture.componentInstance;
    [1, 2, 3].forEach(id => component.toggleRun(id));
    await fixture.whenStable();
    expect(fixture.nativeElement.querySelector('figure')).toBeNull();
    expect(fixture.nativeElement.querySelector('.empty').textContent).toContain('Choose runs');
    fixture.nativeElement.querySelector('input').click();
    await fixture.whenStable();
    expect(component.selected()).toHaveLength(1);
    expect(fixture.nativeElement.querySelector('figure')).not.toBeNull();
  });

  it('uses a common finite scale, including all-missing metrics', () => {
    const component = fixture.componentInstance;
    expect(component.chartMax()).toBeGreaterThanOrEqual(42);
    fixture.componentRef.setInput('runs', [run(1, { metrics: { ...run(1).metrics, output_tokens_per_second: undefined } })]);
    fixture.detectChanges();
    expect(component.chartMax()).toBe(1);
    expect(fixture.nativeElement.querySelector('.chart-bar').style.width).toBe('0%');
    expect(fixture.nativeElement.querySelector('.chart-value').textContent).toContain('—');
  });
});
