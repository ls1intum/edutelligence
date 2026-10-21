import { TestBed } from '@angular/core/testing';
import { BenchmarkResults } from './benchmark-results';
import { ModelProviderBenchmark } from '../../shared/models/provider.model';

function run(id: number, rate: number, baseline?: number, pair = 1): ModelProviderBenchmark {
  return { id, model_provider_id: pair, model_id: 1, model_name: 'Model', provider_id: pair,
    provider_name: 'Worker', dataset: 'openai/gsm8k', sample_size: 50, recorded_at: '2026-10-21T04:00:00Z',
    configuration: baseline ? { nightly: { baseline_id: baseline, parameters: { max_num_seqs: 8 }, original: { max_num_seqs: 4 } } } : {},
    metrics: { request_totals: { successful: 50, total: 50, errored: 0, incomplete: 0 },
      output_tokens_per_second: { successful: { mean: rate, percentiles: { p50: rate, p95: rate, p99: rate } } } } };
}

describe('Benchmark result baseline', () => {
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
