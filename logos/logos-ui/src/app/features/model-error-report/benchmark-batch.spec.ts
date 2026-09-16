import { buildBatch, Sweep, sweepValues } from './benchmark-batch';
import { DEFAULT_BENCHMARK_SETTINGS } from './benchmark-settings';

const sweep = (key: string, values: string): Sweep => ({ key, mode: 'values', values, start: 1, end: 4, step: 1 });
const limits = { gpu_count: 2, gpu_memory_bytes: 24 * 1024 ** 3, current: { tensor_parallel_size: 1, pipeline_parallel_size: 1 } };

describe('Benchmark batch plan', () => {
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
