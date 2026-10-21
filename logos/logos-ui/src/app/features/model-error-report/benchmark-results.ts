import { ChangeDetectionStrategy, Component, computed, input } from '@angular/core';
import { DatePipe, DecimalPipe } from '@angular/common';
import { ModelProviderBenchmark } from '../../shared/models/provider.model';
import { comparisonValue } from './benchmark-comparison';

@Component({
  selector: 'app-benchmark-results',
  standalone: true,
  imports: [DatePipe, DecimalPipe],
  templateUrl: './benchmark-results.html',
  styleUrl: './benchmark-results.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class BenchmarkResults {
  readonly runs = input.required<readonly ModelProviderBenchmark[]>();
  readonly rows = computed(() => [...this.runs()].sort((a, b) => b.id - a.id).map(run => {
    const nightly = run.configuration['nightly'] as {
      baseline_id?: number; parameters?: Record<string, unknown>; original?: Record<string, unknown>;
    } | undefined;
    const baseline = this.runs().find(candidate => candidate.id === nightly?.baseline_id
      && candidate.model_provider_id === run.model_provider_id);
    const isBaseline = baseline?.id === run.id;
    const before = !isBaseline && baseline ? comparisonValue(baseline, 'throughput') : null;
    const after = comparisonValue(run, 'throughput');
    const measurement = run.configuration['measurement'] as { started_at?: string; ended_at?: string } | undefined;
    const requested = run.configuration['requested_overrides'] as Record<string, unknown> | undefined;
    const label = (key: string) => key === 'max_num_seqs' ? 'Sequences' : key === 'max_num_batched_tokens' ? 'Batch tokens' : key;
    const changes = nightly ? Object.entries(nightly?.parameters ?? {}).filter(([key, value]) => value !== nightly?.original?.[key])
      .map(([key, value]) => `${label(key)}: ${nightly?.original?.[key] || 'auto'} → ${value}`)
      : Object.entries(requested ?? {}).map(([key, value]) => `${label(key)} → ${typeof value === 'object' ? JSON.stringify(value) : value}`);
    return { run, before, after, isBaseline, measurement, changes,
      currentSettings: !nightly && requested !== undefined && Object.keys(requested).length === 0,
      kind: nightly ? (isBaseline ? 'Nightly baseline' : 'Nightly variant') : 'Benchmark',
      delta: before !== null && before > 0 && after !== null ? (after / before - 1) * 100 : null };
  }));
}
