import { ModelProviderBenchmark } from '../../shared/models/provider.model';
import { benchmarkConfigurationItems, servingConfigurationItems } from './benchmark-configuration';

export type ComparisonParameter = 'tensor_parallel_size' | 'max_concurrency';

export function comparisonSettings(run: ModelProviderBenchmark): Record<string, string> {
  return Object.fromEntries([...benchmarkConfigurationItems(run), ...servingConfigurationItems(run)]
    .filter(item => item.captured).map(item => [item.key, item.value]));
}

export function parameterValue(run: ModelProviderBenchmark, parameter: ComparisonParameter): number | null {
  const value = Number(comparisonSettings(run)[parameter]);
  return Number.isInteger(value) && value > 0 ? value : null;
}

/** Older reports without the controls needed for isolation cannot establish a baseline. */
export function canCompare(run: ModelProviderBenchmark): boolean {
  const settings = comparisonSettings(run);
  const totals = run.metrics.request_totals;
  return run.sample_size > 0 && totals?.successful === run.sample_size && totals.total === run.sample_size
    && totals.errored === 0 && totals.incomplete === 0
    && ['dataset', 'subset', 'split', 'text_column', 'max_output_tokens', 'seed', 'pipeline_parallel_size']
      .every(key => settings[key] !== undefined)
    && parameterValue(run, 'tensor_parallel_size') !== null && parameterValue(run, 'max_concurrency') !== null
    && (settings['profile'] === 'concurrent'
      || (settings['profile'] === 'synchronous' && parameterValue(run, 'max_concurrency') === 1));
}

function canonical(value: unknown): string {
  if (Array.isArray(value)) return '[' + value.map(canonical).join(',') + ']';
  if (value !== null && typeof value === 'object') {
    return '{' + Object.entries(value).sort(([a], [b]) => a.localeCompare(b))
      .map(([key, item]) => JSON.stringify(key) + ':' + canonical(item)).join(',') + '}';
  }
  return JSON.stringify(value) ?? 'null';
}

function record(value: unknown): Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

function signature(run: ModelProviderBenchmark, parameter: ComparisonParameter): string {
  const settings = comparisonSettings(run);
  delete settings[parameter];
  delete settings['hf_overrides'];
  if (parameter === 'max_concurrency') {
    // Synchronous is the one-stream case. GuideLLM worker count is derived from load.
    delete settings['profile'];
    delete settings['worker_count'];
  }
  const spec = record(record(run.configuration['scenario'])['spec']);
  const backend = record(spec['backend']);
  const serving = record(run.configuration['serving'] ?? run.configuration['serving_configuration'] ?? run.configuration['vllm']);
  // Compare request generation options too, but not per-job URLs, credentials or report paths.
  return canonical({
    provider: run.model_provider_id, model: run.model_id, settings,
    data: spec['data'], mapper: spec['data_column_mapper'], loader: spec['data_loader'],
    body: record(backend['extras'])['body'], seed: spec['seed'],
    warmup: spec['warmup'], cooldown: spec['cooldown'], constraints: spec['constraints'],
    hfOverrides: serving['hf_overrides'],
  });
}

export function isolatedRuns(runs: readonly ModelProviderBenchmark[], baseline: ModelProviderBenchmark,
  parameter: ComparisonParameter): ModelProviderBenchmark[] {
  if (!canCompare(baseline)) return [];
  const expected = signature(baseline, parameter);
  return runs.filter(run => canCompare(run) && signature(run, parameter) === expected)
    .sort((a, b) => parameterValue(a, parameter)! - parameterValue(b, parameter)!
      || Date.parse(a.recorded_at) - Date.parse(b.recorded_at) || a.id - b.id);
}
