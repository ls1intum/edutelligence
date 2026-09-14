import { ChangeDetectionStrategy, Component, computed, input, signal } from '@angular/core';
import { DatePipe } from '@angular/common';
import { ModelProviderBenchmark } from '../../shared/models/provider.model';
import { benchmarkConfigurationItems, servingConfigurationItems } from './benchmark-configuration';

export type ComparisonMetric = 'throughput' | 'ttft' | 'ttlt';

export const COMPARISON_METRICS = [
  { key: 'throughput', label: 'Output throughput', unit: 'tok/s', hint: 'Higher is better' },
  { key: 'ttft', label: 'Mean TTFT', unit: 's', hint: 'Lower is better' },
  { key: 'ttlt', label: 'Mean TTLT', unit: 's', hint: 'Lower is better' },
] as const;

export function comparisonValue(run: ModelProviderBenchmark, metric: ComparisonMetric): number | null {
  if (!(run.metrics.request_totals?.successful > 0)) return null;
  // GuideLLM aggregates output token timings across requests for this rate;
  // it is not the arithmetic mean of the individual requests' token rates.
  const value = metric === 'throughput' ? run.metrics.output_tokens_per_second?.successful?.mean
    : metric === 'ttft' ? run.metrics.time_to_first_token_ms?.successful?.mean
    : run.metrics.request_latency?.successful?.mean;
  if (value == null || !Number.isFinite(value) || value < 0) return null;
  return metric === 'ttft' ? value / 1000 : value;
}

@Component({
  selector: 'app-benchmark-comparison',
  standalone: true,
  imports: [DatePipe],
  templateUrl: './benchmark-comparison.html',
  styleUrl: './benchmark-comparison.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class BenchmarkComparison {
  readonly runs = input.required<readonly ModelProviderBenchmark[]>();
  readonly metrics = COMPARISON_METRICS;
  readonly metric = signal<ComparisonMetric>('throughput');
  readonly selectedIds = signal<readonly number[] | null>(null);
  readonly providerFilter = signal('');
  readonly datasetFilter = signal('');
  readonly orderedRuns = computed(() => [...this.runs()].sort((a, b) =>
    Date.parse(b.recorded_at) - Date.parse(a.recorded_at) || b.id - a.id));
  readonly selected = computed(() => {
    const ids = this.selectedIds();
    return ids === null ? this.orderedRuns().slice(0, 3)
      : this.orderedRuns().filter(run => ids.includes(run.id));
  });
  readonly providers = computed(() => [...new Map(this.orderedRuns().map(run =>
    [run.provider_id, run.provider_name])).entries()]);
  readonly datasets = computed(() => [...new Set(this.runs().map(run => run.dataset))].sort());
  readonly filteredRuns = computed(() => this.orderedRuns().filter(run =>
    (!this.providerFilter() || String(run.provider_id) === this.providerFilter()) &&
    (!this.datasetFilter() || run.dataset === this.datasetFilter())));
  readonly activeMetric = computed(() => this.metrics.find(metric => metric.key === this.metric())!);
  readonly chartRows = computed(() => this.selected().map(run => ({ run, value: comparisonValue(run, this.metric()) })));
  readonly chartMax = computed(() => {
    const max = Math.max(0, ...this.chartRows().map(row => row.value ?? 0));
    if (max === 0) return 1;
    const step = 10 ** Math.floor(Math.log10(max));
    return Math.ceil(max / step) * step;
  });
  readonly differentInputs = computed(() => new Set(this.selected().map(run => JSON.stringify(
    benchmarkConfigurationItems(run).filter(item => [
      'dataset', 'subset', 'split', 'text_column', 'sample_size', 'max_output_tokens', 'seed',
    ].includes(item.key)).map(item => item.value),
  ))).size > 1);

  isSelected(id: number): boolean { return this.selected().some(run => run.id === id); }

  toggleRun(id: number): void {
    const ids = this.selected().map(run => run.id);
    this.selectedIds.set(ids.includes(id) ? ids.filter(value => value !== id)
      : ids.length < 5 ? [...ids, id] : ids);
  }

  format(value: number | null): string {
    if (value === null) return '—';
    if (value > 0 && value < 0.001) return '<0.001';
    return value.toLocaleString(undefined, { maximumFractionDigits: 3 });
  }

  value(run: ModelProviderBenchmark, metric: ComparisonMetric): string {
    return this.format(comparisonValue(run, metric));
  }

  datasetDetails(run: ModelProviderBenchmark): string {
    const items = benchmarkConfigurationItems(run);
    return ['subset', 'split', 'max_output_tokens'].map(key => {
      const item = items.find(item => item.key === key)!;
      return key === 'max_output_tokens' ? `Max output tokens: ${item.value}` : item.value;
    }).join(' · ');
  }

  configuration(run: ModelProviderBenchmark): string {
    const items = [...benchmarkConfigurationItems(run), ...servingConfigurationItems(run)];
    return [['profile', 'Profile'], ['max_concurrency', 'Concurrency'],
      ['tensor_parallel_size', 'TP'], ['pipeline_parallel_size', 'PP']]
      .map(([key, label]) => `${label}: ${items.find(item => item.key === key)!.value}`).join(' · ');
  }
}
