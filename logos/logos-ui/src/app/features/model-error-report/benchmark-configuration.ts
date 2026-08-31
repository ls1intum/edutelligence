import { ModelProviderBenchmark } from '../../shared/models/provider.model';

export interface BenchmarkConfigurationItem {
  readonly key: string;
  readonly label: string;
  readonly value: string;
  readonly captured: boolean;
}

export interface BenchmarkConfigurationRow {
  readonly benchmark: BenchmarkConfigurationItem | null;
  readonly serving: BenchmarkConfigurationItem | null;
}

const NOT_CAPTURED = 'Not captured';

type JsonPath = readonly (string | number)[];

export function benchmarkConfigurationItems(
  benchmark: ModelProviderBenchmark,
): readonly BenchmarkConfigurationItem[] {
  const configuration = benchmark.configuration;

  return [
    item('dataset', 'Dataset', benchmark.dataset),
    item('subset', 'Subset', first(configuration, [
      ['scenario', 'spec', 'data', 0, 'load_kwargs', 'name'],
    ])),
    item('split', 'Split', first(configuration, [
      ['scenario', 'spec', 'data', 0, 'load_kwargs', 'split'],
    ])),
    item('sample_size', 'Sample size', benchmark.sample_size),
    item('profile', 'Profile', first(configuration, [
      ['benchmark', 'profile', 'kind'],
      ['scenario', 'spec', 'profile', 'kind'],
    ])),
    item('max_concurrency', 'Max concurrency', first(configuration, [
      ['benchmark', 'strategy', 'max_concurrency'],
    ])),
    item('worker_count', 'Worker count', first(configuration, [
      ['benchmark', 'strategy', 'worker_count'],
      ['scenario', 'spec', 'data_loader', 'num_workers'],
    ])),
    item('max_output_tokens', 'Max output tokens', first(configuration, [
      ['scenario', 'spec', 'backend', 'extras', 'body', 'max_tokens'],
      ['benchmark', 'backend', 'extras', 'body', 'max_tokens'],
    ])),
    item('seed', 'Seed', first(configuration, [
      ['scenario', 'spec', 'seed', 'value'],
    ])),
    item('request_format', 'Request format', first(configuration, [
      ['scenario', 'spec', 'backend', 'request_format'],
      ['benchmark', 'backend', 'request_format'],
    ])),
    item('streaming', 'Streaming', first(configuration, [
      ['scenario', 'spec', 'backend', 'stream'],
      ['benchmark', 'backend', 'stream'],
    ])),
    item('guidellm_version', 'GuideLLM version', first(configuration, [
      ['metadata', 'guidellm_version'],
    ])),
  ];
}

export function servingConfigurationItems(
  benchmark: ModelProviderBenchmark,
): readonly BenchmarkConfigurationItem[] {
  const serving = servingConfiguration(benchmark.configuration);

  return [
    item('tensor_parallel_size', 'Tensor parallel size', field(serving, 'tensor_parallel_size')),
    item('pipeline_parallel_size', 'Pipeline parallel size', field(serving, 'pipeline_parallel_size')),
    item('kv_cache_dtype', 'KV cache dtype', field(serving, 'kv_cache_dtype')),
    item('kv_cache_memory', 'KV cache memory', first(serving, [
      ['kv_cache_memory_bytes'],
      ['kv_cache_memory'],
    ])),
    item('max_num_seqs', 'Max sequences', field(serving, 'max_num_seqs')),
    item('max_num_batched_tokens', 'Max batched tokens', field(serving, 'max_num_batched_tokens')),
    item('enable_prefix_caching', 'Prefix caching', field(serving, 'enable_prefix_caching')),
    item('max_model_len', 'Max model length', field(serving, 'max_model_len')),
    item(
      'gpu_memory_utilization',
      'GPU memory utilization',
      field(serving, 'gpu_memory_utilization'),
      formatGpuUtilization,
    ),
    item('quantization', 'Quantization', field(serving, 'quantization')),
    item('dtype', 'Data type', field(serving, 'dtype')),
    item('enforce_eager', 'Eager execution', field(serving, 'enforce_eager')),
    item(
      'disable_custom_all_reduce',
      'Disable custom all-reduce',
      field(serving, 'disable_custom_all_reduce'),
    ),
    item('hf_overrides', 'Hugging Face overrides', field(serving, 'hf_overrides')),
  ];
}

export function benchmarkConfigurationRows(
  benchmark: ModelProviderBenchmark,
): readonly BenchmarkConfigurationRow[] {
  const benchmarkItems = benchmarkConfigurationItems(benchmark);
  const servingItems = servingConfigurationItems(benchmark);
  const rowCount = Math.max(benchmarkItems.length, servingItems.length);

  return Array.from({ length: rowCount }, (_, index) => ({
    benchmark: benchmarkItems[index] ?? null,
    serving: servingItems[index] ?? null,
  }));
}

export function servingCommand(benchmark: ModelProviderBenchmark): string | null {
  const command = field(servingConfiguration(benchmark.configuration), 'command');
  return typeof command === 'string' && command.trim() ? command.trim() : null;
}

function servingConfiguration(configuration: Record<string, unknown>): Record<string, unknown> {
  const value = first(configuration, [
    ['serving'],
    ['serving_configuration'],
    ['vllm'],
  ]);
  return isRecord(value) ? value : {};
}

function item(
  key: string,
  label: string,
  rawValue: unknown,
  formatter: (value: unknown) => string = formatValue,
): BenchmarkConfigurationItem {
  const captured = isCaptured(rawValue);
  return {
    key,
    label,
    value: captured ? formatter(rawValue) : NOT_CAPTURED,
    captured,
  };
}

function first(value: unknown, paths: readonly JsonPath[]): unknown {
  for (const path of paths) {
    const candidate = atPath(value, path);
    if (isCaptured(candidate)) return candidate;
  }
  return undefined;
}

function field(value: unknown, key: string): unknown {
  return isRecord(value) ? value[key] : undefined;
}

function atPath(value: unknown, path: JsonPath): unknown {
  let current = value;
  for (const segment of path) {
    if (typeof segment === 'number') {
      if (!Array.isArray(current)) return undefined;
      current = current[segment];
    } else {
      if (!isRecord(current)) return undefined;
      current = current[segment];
    }
  }
  return current;
}

function formatValue(value: unknown): string {
  if (typeof value === 'boolean') return value ? 'Enabled' : 'Disabled';
  if (typeof value === 'string') return value;
  if (typeof value === 'number') return String(value);
  return JSON.stringify(value) ?? String(value);
}

function formatGpuUtilization(value: unknown): string {
  if (typeof value !== 'number') return formatValue(value);
  return `${value} (${Math.round(value * 100)}%)`;
}

function isCaptured(value: unknown): boolean {
  return value !== undefined && value !== null && value !== '';
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}
