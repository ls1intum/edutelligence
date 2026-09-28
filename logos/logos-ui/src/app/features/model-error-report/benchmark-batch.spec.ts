import { buildBatch, Sweep, sweepValues } from './benchmark-batch';
import { DEFAULT_BENCHMARK_SETTINGS } from './benchmark-settings';

const sweep = (key: string, values: string): Sweep => ({ key, mode: 'values', values, start: 1, end: 4, step: 1 });
const limits = { gpu_count: 2, gpu_memory_bytes: 24 * 1024 ** 3, current: { tensor_parallel_size: 1, pipeline_parallel_size: 1 } };

describe('Benchmark batch plan', () => {
  it('varies attention backends while keeping the other controls fixed', () => {
    const settings = { ...DEFAULT_BENCHMARK_SETTINGS, serving_overrides: { tensor_parallel_size: 2 } };
    const batch = buildBatch(settings, 50, [sweep('attention_backend', 'FLASHINFER,FLASH_ATTN,TRITON_ATTN,FLEX_ATTENTION')], 3, limits, true);
    expect(batch.configurations.map(s => s.serving_overrides['attention_backend'])).toEqual(['FLASHINFER', 'FLASH_ATTN', 'TRITON_ATTN', 'FLEX_ATTENTION']);
    expect(batch.configurations.every(s => s.serving_overrides['tensor_parallel_size'] === 2 && s.samples === 50)).toBe(true);
    expect(batch.repetitions).toBe(3);
    expect(settings.serving_overrides).toEqual({ tensor_parallel_size: 2 });
    expect(() => buildBatch(settings, 50, [sweep('attention_backend', 'typo')], 3, limits, true)).toThrow(/Attention backend/);
  });
  it('validates TURBOQUANT against the effective KV cache setting', () => {
    const backend = [sweep('attention_backend', 'TURBOQUANT')];
    expect(() => buildBatch(DEFAULT_BENCHMARK_SETTINGS, 5, backend, 1, limits, true)).toThrow(/turboquant KV cache dtype/);
    const settings = { ...DEFAULT_BENCHMARK_SETTINGS, serving_overrides: { kv_cache_dtype: 'turboquant_k8v4' } };
    expect(buildBatch(settings, 5, backend, 2, limits, true).configurations[0].serving_overrides['attention_backend']).toBe('TURBOQUANT');
  });
  it('creates all combinations with fixed controls and supports more than 15 runs', () => {
    const settings = { ...DEFAULT_BENCHMARK_SETTINGS, seed: 17, serving_overrides: { pipeline_parallel_size: 1, enable_prefix_caching: false } };
    const batch = buildBatch(settings, 50, [sweep('concurrency', '1,4,16'), sweep('tensor_parallel_size', '1,2')], 5, limits, true);
    expect(batch.configurations).toHaveLength(6);
    expect(batch.configurations.length * batch.repetitions).toBe(30);
    expect(batch.configurations.map(s => [s.concurrency, s.serving_overrides['tensor_parallel_size']])).toEqual([[1,1],[1,2],[4,1],[4,2],[16,1],[16,2]]);
    expect(batch.configurations.every(s => s.seed === 17 && s.samples === 50 && s.profile === 'concurrent' && s.serving_overrides['enable_prefix_caching'] === false)).toBe(true);
    expect(settings).toEqual({ ...DEFAULT_BENCHMARK_SETTINGS, seed: 17, serving_overrides: { pipeline_parallel_size: 1, enable_prefix_caching: false } });
  });
  it('supports repeated fixed configurations and decimal ranges', () => {
    expect(buildBatch(DEFAULT_BENCHMARK_SETTINGS, 5, [], 40, null, false).configurations).toHaveLength(1);
    expect(sweepValues({ ...sweep('gpu_memory_utilization', ''), mode: 'range', start: .6, end: .9, step: .1 })).toEqual([.6, .7, .8, .9]);
    expect(sweepValues(sweep('enable_prefix_caching', 'false,true,false'))).toEqual([false, true]);
  });
  it.each(['1,,4', '0', '1.5', 'Infinity', '33'])('rejects invalid concurrency values %s', values => {
    expect(() => sweepValues(sweep('concurrency', values))).toThrow();
  });
  it('rejects invalid hardware combinations before starting any run', () => {
    expect(() => buildBatch(DEFAULT_BENCHMARK_SETTINGS, 5, [sweep('tensor_parallel_size', '1,2,3')], 3, limits, true)).toThrow(/requires 3 GPUs/);
    expect(() => buildBatch(DEFAULT_BENCHMARK_SETTINGS, 5, [sweep('tensor_parallel_size', '1')], 1, null, false)).toThrow(/Logos worker/);
  });
  it('rejects zero steps, duplicates and excessive plans without allocating repetitions', () => {
    expect(() => sweepValues({ ...sweep('concurrency', ''), mode: 'range', step: 0 })).toThrow();
    expect(() => buildBatch(DEFAULT_BENCHMARK_SETTINGS, 5, [sweep('seed', '1'), sweep('seed', '2')], 2, null, false)).toThrow(/once/);
    expect(() => buildBatch(DEFAULT_BENCHMARK_SETTINGS, 5, [sweep('seed', '1,2')], 6000, null, false)).toThrow(/10,000/);
  });
});


it('rejects backend sweeps that inherit an incompatible TurboQuant cache', () => {
  const limits = { gpu_count: 2, gpu_memory_bytes: null, current: { kv_cache_dtype: 'turboquant_k8v4' } };
  const backend = [{ key: 'attention_backend', mode: 'values' as const, values: 'FLASH_ATTN,TRITON_ATTN', start: 0, end: 0, step: 1 }];
  expect(() => buildBatch(DEFAULT_BENCHMARK_SETTINGS, 5, backend, 1, limits, true)).toThrow(/TurboQuant KV cache requires/);
});
