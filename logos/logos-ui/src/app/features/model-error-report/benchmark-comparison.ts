import { ChangeDetectionStrategy, Component, computed, input, signal } from '@angular/core';
import { DatePipe } from '@angular/common';
import { ModelProviderBenchmark } from '../../shared/models/provider.model';
import { benchmarkConfigurationItems, servingConfigurationItems } from './benchmark-configuration';
import { canCompare, comparisonSettings, isolatedRuns, parameterValue } from './benchmark-isolation';

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
  readonly baselineId = signal<number | null>(null);
  readonly orderedRuns = computed(() => [...this.runs()].sort((a, b) =>
    Date.parse(b.recorded_at) - Date.parse(a.recorded_at) || b.id - a.id));
  readonly eligibleRuns = computed(() => this.orderedRuns().filter(canCompare));
  readonly baseline = computed(() => this.eligibleRuns().find(run => run.id === this.baselineId())
    ?? this.eligibleRuns().find(run => run.dataset === 'openai/gsm8k' && run.sample_size === 50
      && parameterValue(run, 'tensor_parallel_size') === 1 && parameterValue(run, 'max_concurrency') === 4)
    ?? this.eligibleRuns()[0] ?? null);
  readonly baselineSettings = computed(() => this.baseline() ? comparisonSettings(this.baseline()!) : {});
  readonly activeMetric = computed(() => this.metrics.find(metric => metric.key === this.metric())!);
  readonly charts = computed(() => {
    const baseline = this.baseline();
    if (!baseline) return [];
    return ([
      { key: 'tensor_parallel_size', label: 'Tensor parallelism', fixed: `Concurrency fixed at ${this.baselineSettings()['max_concurrency']}` },
      { key: 'max_concurrency', label: 'Concurrent requests', fixed: `TP fixed at ${this.baselineSettings()['tensor_parallel_size']}` },
    ] as const).map(parameter => {
      const runs = isolatedRuns(this.orderedRuns(), baseline, parameter.key);
      const values = [...new Set(runs.map(run => parameterValue(run, parameter.key)!))];
      return { ...parameter, groups: values.map(value => ({ parameter: value,
        rows: runs.filter(run => parameterValue(run, parameter.key) === value)
          .map(run => ({ run, value: comparisonValue(run, this.metric()) })),
      })) };
    });
  });
  readonly selected = computed(() => [...new Map(this.charts().flatMap(chart => chart.groups)
    .flatMap(group => group.rows).map(row => [row.run.id, row.run])).values()]);
  readonly excludedCount = computed(() => this.runs().length - this.selected().length);
  readonly chartMax = computed(() => {
    const max = Math.max(0, ...this.selected().map(run => comparisonValue(run, this.metric()) ?? 0));
    if (max === 0) return 1;
    const step = 10 ** Math.floor(Math.log10(max));
    return Math.ceil(max / step) * step;
  });

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
