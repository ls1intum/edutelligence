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
  preview_columns?: string[];
  preview_rows?: { row_index: number; cells: Record<string, string | null>; truncated_columns: string[] }[];
}

/** Keep the viewer on the same configuration and split as the benchmark draft. */
export function datasetViewerUrl(settings: Pick<BenchmarkSettings, 'dataset' | 'subset' | 'split'>): string {
  const dataset = settings.dataset.split('/').map(encodeURIComponent).join('/');
  return `https://huggingface.co/datasets/${dataset}/viewer/${encodeURIComponent(settings.subset)}/${encodeURIComponent(settings.split)}`;
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

export interface BenchmarkWorkerLimits {
  gpu_count: number | null;
  gpu_memory_bytes: number | null;
  current: Record<string, unknown>;
}

export const SERVING_CHOICES: Record<string, readonly string[]> = {
  dtype: ['auto', 'float16', 'bfloat16', 'float32', 'half', 'float'],
  kv_cache_dtype: ['auto', 'fp8', 'fp8_e4m3', 'fp8_e5m2'],
};

export function servingValidationErrors(settings: BenchmarkSettings, limits: BenchmarkWorkerLimits | null): string[] {
  const overrides = settings.serving_overrides;
  if (!Object.keys(overrides).length) return [];
  const errors: string[] = [];
  for (const field of SERVING_FIELDS) {
    const value = overrides[field.key];
    if (value == null) continue;
    if (field.type === 'number') {
      const n = Number(value);
      const max = 'max' in field ? field.max : null;
      if (!Number.isFinite(n) || n < field.min || (max != null && n > max) || (!('step' in field) && !Number.isInteger(n))) {
        errors.push(`${field.label}: enter ${'step' in field ? 'a number' : 'an integer'} from ${field.min}${max == null ? '' : ` to ${max}`}.`);
      }
    }
    const choices = SERVING_CHOICES[field.key];
    if (choices && !choices.includes(String(value))) errors.push(`${field.label}: choose a supported value.`);
  }
  if (limits?.gpu_count == null) return [...errors, 'Worker GPU limits are unavailable. Reload the limits before changing vLLM settings.'];
  if (limits.gpu_count === 0) return [...errors, 'No NVIDIA GPUs are available for this model on the selected worker.'];
  const effective = { ...limits.current, ...overrides };
  const tp = Number(effective['tensor_parallel_size'] ?? 1);
  const pp = Number(effective['pipeline_parallel_size'] ?? 1);
  if (tp * pp > limits.gpu_count) errors.push(`TP ${tp} × PP ${pp} requires ${tp * pp} GPUs; this worker provides ${limits.gpu_count} for this model.`);
  const sequences = Number(effective['max_num_seqs'] ?? 0);
  const batched = Number(effective['max_num_batched_tokens'] ?? 0);
  if (sequences > 0 && batched > 0 && batched < sequences) errors.push('Max batched tokens must be at least max sequences.');
  const cache = String(overrides['kv_cache_memory_bytes'] ?? '');
  if (cache) {
    const match = /^(\d+(?:\.\d+)?)([KMG]?)$/i.exec(cache);
    const bytes = match ? Number(match[1]) * ({ K: 1024, M: 1024 ** 2, G: 1024 ** 3 }[match[2].toUpperCase()] ?? 1) : NaN;
    if (!Number.isFinite(bytes) || bytes <= 0) errors.push('KV cache memory: use a positive byte count or a value such as 512M or 4G.');
    else if (limits.gpu_memory_bytes != null && bytes >= limits.gpu_memory_bytes) errors.push('KV cache memory must be smaller than GPU memory; model weights also need space.');
  }
  return errors;
}
