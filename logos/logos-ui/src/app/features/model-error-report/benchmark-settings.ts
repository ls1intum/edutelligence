import { ModelProviderBenchmark } from '../../shared/models/provider.model';

export interface BenchmarkSettings {
  dataset: string;
  subset: string;
  split: string;
  text_column: string;
  profile: 'synchronous' | 'concurrent';
  concurrency: number;
  seed: number;
  max_output_tokens: number;
  serving_overrides: Record<string, unknown>;
}

export const DEFAULT_BENCHMARK_SETTINGS: BenchmarkSettings = {
  dataset: 'openai/gsm8k', subset: 'main', split: 'test', text_column: 'question',
  profile: 'synchronous', concurrency: 1, seed: 42, max_output_tokens: 512, serving_overrides: {},
};

export interface DatasetMetadata {
  dataset: string;
  subset: string;
  split: string;
  splits: { subset: string; split: string }[];
  text_columns: string[];
}

export const SERVING_FIELDS = [
  { key: 'tensor_parallel_size', label: 'Tensor parallel size', type: 'number', min: 1, max: 64 },
  { key: 'pipeline_parallel_size', label: 'Pipeline parallel size', type: 'number', min: 1, max: 64 },
  { key: 'gpu_memory_utilization', label: 'GPU memory utilization', type: 'number', min: 0.1, max: 1, step: 0.01 },
  { key: 'kv_cache_memory_bytes', label: 'KV cache memory per GPU (e.g. 4G)', type: 'text' },
  { key: 'kv_cache_dtype', label: 'KV cache dtype', type: 'text' },
  { key: 'max_num_seqs', label: 'Max sequences (0 = auto)', type: 'number', min: 0, max: 65536 },
  { key: 'max_num_batched_tokens', label: 'Max batched tokens', type: 'number', min: 1 },
  { key: 'max_model_len', label: 'Max model length (0 = auto)', type: 'number', min: 0 },
  { key: 'dtype', label: 'Data type', type: 'text' },
  { key: 'quantization', label: 'Quantization', type: 'text' },
  { key: 'enable_prefix_caching', label: 'Prefix caching', type: 'boolean' },
  { key: 'enforce_eager', label: 'Eager execution', type: 'boolean' },
  { key: 'disable_custom_all_reduce', label: 'Disable custom all-reduce', type: 'boolean' },
] as const;

/** Use captured settings as a new draft; the recorded benchmark stays immutable. */
export function settingsFromBenchmark(benchmark: ModelProviderBenchmark): BenchmarkSettings {
  const config = benchmark.configuration as any;
  const spec = config.scenario?.spec ?? {};
  const data = spec.data?.[0] ?? {};
  const profile = spec.profile ?? config.benchmark?.profile ?? {};
  const serving = config.serving ?? config.serving_configuration ?? config.vllm ?? {};
  const overrides: Record<string, unknown> = {};
  for (const { key } of SERVING_FIELDS) {
    const value = serving[key] ?? (key === 'kv_cache_memory_bytes' ? serving.kv_cache_memory : undefined);
    if (value !== null && value !== undefined && value !== '') overrides[key] = key === 'kv_cache_memory_bytes' ? String(value) : structuredClone(value);
  }
  if (serving.hf_overrides && typeof serving.hf_overrides === 'object') overrides['hf_overrides'] = structuredClone(serving.hf_overrides);
  return {
    ...DEFAULT_BENCHMARK_SETTINGS,
    dataset: benchmark.dataset,
    subset: data.load_kwargs?.name ?? DEFAULT_BENCHMARK_SETTINGS.subset,
    split: data.load_kwargs?.split ?? DEFAULT_BENCHMARK_SETTINGS.split,
    text_column: spec.data_column_mapper?.column_mappings?.text_column ?? DEFAULT_BENCHMARK_SETTINGS.text_column,
    profile: profile.kind === 'concurrent' ? 'concurrent' : 'synchronous',
    concurrency: typeof profile.streams === 'number' ? profile.streams : Array.isArray(profile.streams) ? profile.streams[0] : 1,
    max_output_tokens: spec.backend?.extras?.body?.max_tokens ?? config.benchmark?.backend?.extras?.body?.max_tokens ?? 512,
    seed: spec.seed?.value ?? 42,
    serving_overrides: overrides,
  };
}
