import { ChangeDetectionStrategy, Component, computed, input, signal } from '@angular/core';
import { DatePipe } from '@angular/common';
import { ModelProviderBenchmark } from '../../shared/models/provider.model';
import { benchmarkConfigurationItems, servingConfigurationItems } from './benchmark-configuration';
import { canCompare, comparisonSettings, isolatedRuns, parameterValue } from './benchmark-isolation';

export type ComparisonMetric = 'throughput' | 'ttft' | 'ttlt';
type RunSortKey = 'id' | 'recorded_at' | 'tensor_parallel_size' | 'max_concurrency' | 'sample_size' | ComparisonMetric;


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

/** Tukey boxplot across run-level measurements, using interpolated quartiles. */
export function boxplot(values: readonly (number | null)[]) {
  const sorted = values.filter((value): value is number => value !== null && Number.isFinite(value) && value >= 0).sort((a, b) => a - b);
  if (!sorted.length) return null;
  const quantile = (p: number) => {
    const position = (sorted.length - 1) * p;
    const lower = Math.floor(position);
    return sorted[lower] + (sorted[Math.ceil(position)] - sorted[lower]) * (position - lower);
  };
  const q1 = quantile(.25), median = quantile(.5), q3 = quantile(.75);
  const iqr = q3 - q1;
  const low = sorted.find(value => value >= q1 - 1.5 * iqr)!;
  const high = [...sorted].reverse().find(value => value <= q3 + 1.5 * iqr)!;
  return { count: sorted.length, q1, median, q3, low, high,
    outliers: [...new Set(sorted.filter(value => value < low || value > high))] };
}

export interface ChartScale { min: number; max: number; span: number; ticks: number[]; }

/** Fit every observation, including outliers, with 10% of the data range on each side. */
export function fitChartScale(values: readonly (number | null)[]): ChartScale {
  const measured = values.filter((value): value is number => value !== null && Number.isFinite(value) && value >= 0);
  const low = measured.length ? Math.min(...measured) : 0;
  const high = measured.length ? Math.max(...measured) : 1;
  // Identical measurements still need a nonzero axis; center the line in the plot.
  const padding = ((high - low) || Math.abs(high) || 1) * .1;
  const min = low - padding;
  const max = high + padding;
  const span = max - min;
  return { min, max, span, ticks: Array.from({ length: 5 }, (_, i) => max - span * i / 4) };
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
  readonly columns: readonly { key: RunSortKey; label: string; unit?: string }[] = [
    { key: 'id', label: 'Run' }, { key: 'recorded_at', label: 'Date' },
    { key: 'tensor_parallel_size', label: 'TP' }, { key: 'max_concurrency', label: 'Concurrency' },
    { key: 'sample_size', label: 'Requests' },
    { key: 'throughput', label: 'Output', unit: 'tok/s' },
    { key: 'ttft', label: 'Mean TTFT', unit: 's' }, { key: 'ttlt', label: 'Mean TTLT', unit: 's' },
  ];
  readonly sortKey = signal<RunSortKey>('recorded_at');
  readonly sortDirection = signal<'ascending' | 'descending'>('descending');
  readonly sortedRuns = computed(() => [...this.selected()].sort((a, b) => {
    const left = this.sortValue(a, this.sortKey());
    const right = this.sortValue(b, this.sortKey());
    // Missing measurements stay last in either direction.
    if (left === null || right === null) return left === right ? b.id - a.id : left === null ? 1 : -1;
    return (left - right) * (this.sortDirection() === 'ascending' ? 1 : -1) || b.id - a.id;
  }));
  readonly showRuns = signal(false);
  readonly visibleRunCount = signal(50);
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
      return { ...parameter, minPlotWidth: values.length * 68 + 72,
        scale: fitChartScale(runs.map(run => comparisonValue(run, this.metric()))),
        groups: values.map(value => {
          const rows = runs.filter(run => parameterValue(run, parameter.key) === value)
            .map(run => ({ run, value: comparisonValue(run, this.metric()) }));
          return { parameter: value, rows, box: boxplot(rows.map(row => row.value)) };
        }) };
    });
  });
  readonly selected = computed(() => [...new Map(this.charts().flatMap(chart => chart.groups)
    .flatMap(group => group.rows).map(row => [row.run.id, row.run])).values()]);
  readonly excludedCount = computed(() => this.runs().length - this.selected().length);
  position(value: number, scale: ChartScale): number {
    return (value - scale.min) / scale.span * 100;
  }

  axisValue(value: number, scale: ChartScale): string {
    const digits = Math.min(20, Math.max(0, Math.ceil(-Math.log10(scale.span / 4)) + 1));
    return value.toLocaleString(undefined, { maximumFractionDigits: digits });
  }

  boxLabel(box: NonNullable<ReturnType<typeof boxplot>>): string {
    return `${box.count} runs · median ${this.format(box.median)} · Q1 ${this.format(box.q1)} · Q3 ${this.format(box.q3)} · whiskers ${this.format(box.low)}–${this.format(box.high)} ${this.activeMetric().unit} · ${box.outliers.length} distinct outlier values`;
  }

  sortBy(key: RunSortKey): void {
    this.sortDirection.set(this.sortKey() === key && this.sortDirection() === 'ascending' ? 'descending' : 'ascending');
    this.sortKey.set(key);
  }

  sortValue(run: ModelProviderBenchmark, key: RunSortKey): number | null {
    if (key === 'id' || key === 'sample_size') return run[key];
    if (key === 'recorded_at') {
      const timestamp = Date.parse(run.recorded_at);
      return Number.isFinite(timestamp) ? timestamp : null;
    }
    if (key === 'tensor_parallel_size' || key === 'max_concurrency') return parameterValue(run, key);
    return comparisonValue(run, key);
  }

  sortLabel(key: RunSortKey): string {
    const direction = this.sortKey() === key && this.sortDirection() === 'ascending' ? 'descending' : 'ascending';
    return `Sort ${this.columns.find(column => column.key === key)!.label} ${direction}`;
  }

  chartValue(value: number | null): string {
    return value === null || (value > 0 && value < 0.01) ? this.format(value)
      : value.toLocaleString(undefined, { maximumFractionDigits: 2 });
  }

  format(value: number | null): string {
    if (value === null) return '—';
    if (value > 0 && value < 0.001) return '<0.001';
    return value.toLocaleString(undefined, { maximumFractionDigits: 3 });
  }

  value(run: ModelProviderBenchmark, metric: ComparisonMetric): string {
    return this.format(comparisonValue(run, metric));
  }

  configuration(run: ModelProviderBenchmark): string {
    const items = [...benchmarkConfigurationItems(run), ...servingConfigurationItems(run)];
    return [['profile', 'Profile'], ['max_concurrency', 'Concurrency'],
      ['tensor_parallel_size', 'TP'], ['pipeline_parallel_size', 'PP']]
      .map(([key, label]) => `${label}: ${items.find(item => item.key === key)!.value}`).join(' · ');
  }
}
