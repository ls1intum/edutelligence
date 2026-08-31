import { ModelProviderBenchmark } from '../../shared/models/provider.model';
import {
  benchmarkConfigurationItems,
  benchmarkConfigurationRows,
  servingCommand,
  servingConfigurationItems,
} from './benchmark-configuration';

const makeBenchmark = (
  configuration: Record<string, unknown>,
): ModelProviderBenchmark => ({
  id: 1,
  model_provider_id: 3,
  provider_id: 4,
  provider_name: 'hochbruegge',
  model_id: 3,
  model_name: 'Qwen/Qwen2.5-Coder-7B-Instruct-AWQ',
  configuration,
  dataset: 'openai/gsm8k',
  sample_size: 5,
  metrics: {
    request_totals: { successful: 5, incomplete: 0, errored: 0, total: 5 },
  },
  recorded_at: '2026-08-27T10:56:13Z',
});

describe('benchmarkConfigurationItems', () => {
  it('extracts the effective GuideLLM setup from an imported report', () => {
    const benchmark = makeBenchmark({
      metadata: { guidellm_version: '0.7.2' },
      scenario: {
        spec: {
          data: [{ load_kwargs: { name: 'main', split: 'test' } }],
          seed: { value: 42 },
          backend: {
            request_format: '/v1/chat/completions',
            stream: true,
            extras: { body: { max_tokens: 512 } },
          },
        },
      },
      benchmark: {
        profile: { kind: 'synchronous' },
        strategy: { max_concurrency: 1, worker_count: 1 },
      },
    });

    expect(Object.fromEntries(
      benchmarkConfigurationItems(benchmark).map(item => [item.key, item.value]),
    )).toMatchObject({
      dataset: 'openai/gsm8k',
      subset: 'main',
      split: 'test',
      sample_size: '5',
      profile: 'synchronous',
      max_concurrency: '1',
      worker_count: '1',
      max_output_tokens: '512',
      seed: '42',
      request_format: '/v1/chat/completions',
      streaming: 'Enabled',
      guidellm_version: '0.7.2',
    });
  });
});

describe('servingConfigurationItems', () => {
  it('shows missing serving values without inventing vLLM defaults', () => {
    const items = servingConfigurationItems(makeBenchmark({}));
    expect(items.every(item => item.value === 'Not captured')).toBe(true);
    expect(items.every(item => item.captured === false)).toBe(true);
  });

  it('reads a captured vLLM snapshot and formats booleans and utilization', () => {
    const benchmark = makeBenchmark({
      serving: {
        command: 'vllm serve Qwen/Qwen2.5-Coder-7B-Instruct-AWQ --tensor-parallel-size 2',
        tensor_parallel_size: 2,
        enable_prefix_caching: true,
        gpu_memory_utilization: 0.9,
        quantization: 'awq',
      },
    });
    const values = Object.fromEntries(
      servingConfigurationItems(benchmark).map(item => [item.key, item.value]),
    );

    expect(values['tensor_parallel_size']).toBe('2');
    expect(values['enable_prefix_caching']).toBe('Enabled');
    expect(values['gpu_memory_utilization']).toBe('0.9 (90%)');
    expect(values['quantization']).toBe('awq');
    expect(servingCommand(benchmark)).toContain('--tensor-parallel-size 2');
  });
});

describe('benchmarkConfigurationRows', () => {
  it('pairs benchmark and serving values into shared visual rows', () => {
    const rows = benchmarkConfigurationRows(makeBenchmark({}));

    expect(rows[0].benchmark?.key).toBe('dataset');
    expect(rows[0].serving?.key).toBe('tensor_parallel_size');
    expect(rows.at(-1)?.benchmark).toBeNull();
    expect(rows.at(-1)?.serving?.key).toBe('hf_overrides');
  });
});
