import { TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting, HttpTestingController } from '@angular/common/http/testing';
import { ModelManagementService } from '../../core/services/model-management.service';
import { ModelProviderBenchmark } from '../../shared/models/provider.model';
import { DEFAULT_BENCHMARK_SETTINGS, settingsFromBenchmark } from './benchmark-settings';

const recorded = {
  dataset: 'org/prompts', sample_size: 12,
  configuration: {
    scenario: { spec: { data: [{ load_kwargs: { name: 'default', split: 'validation' } }],
      data_column_mapper: { column_mappings: { text_column: 'prompt' } },
      profile: { kind: 'concurrent', streams: [4] }, seed: { value: 7 },
      backend: { extras: { body: { max_tokens: 123 } } } } },
    serving: { tensor_parallel_size: 2, enable_prefix_caching: false, kv_cache_memory: 1024,
      command: 'vllm serve model', hf_overrides: { nested: { value: 1 } } },
  },
} as unknown as ModelProviderBenchmark;

describe('Next benchmark settings', () => {
  it('copies the recorded dataset, normalized concurrency and serving values into an independent draft', () => {
    const draft = settingsFromBenchmark(recorded);
    expect(draft).toMatchObject({ dataset: 'org/prompts', subset: 'default', split: 'validation',
      text_column: 'prompt', profile: 'concurrent', concurrency: 4, seed: 7, max_output_tokens: 123,
      serving_overrides: { enable_prefix_caching: false, kv_cache_memory_bytes: '1024' } });
    expect(draft.serving_overrides['command']).toBeUndefined();
    (draft.serving_overrides['hf_overrides'] as any).nested.value = 2;
    expect((recorded.configuration['serving'] as any).hf_overrides.nested.value).toBe(1);
  });

  it('uses editable defaults for old reports with no captured settings', () => {
    const draft = settingsFromBenchmark({ ...recorded, dataset: 'openai/gsm8k', configuration: {} });
    expect(draft).toEqual(DEFAULT_BENCHMARK_SETTINGS);
  });

  it('sends the edited draft to the API rather than fixed GSM8K settings', async () => {
    TestBed.configureTestingModule({ providers: [provideHttpClient(), provideHttpClientTesting()] });
    const service = TestBed.inject(ModelManagementService);
    const http = TestBed.inject(HttpTestingController);
    const draft = settingsFromBenchmark(recorded);
    const pending = service.startBenchmark(31, 12, draft);
    const request = http.expectOne('/api/logosdb/model_benchmarks/run');
    expect(request.request.body).toEqual({ model_provider_id: 31, sample_size: 12, ...draft });
    request.flush({ job_id: 7, status: 'pending' });
    await pending;
    http.verify();
  });
});

import { BenchmarkSettingsEditor } from './benchmark-settings-editor';

describe('Benchmark settings editor values', () => {
  it('converts numeric worker settings and preserves explicit false', () => {
    TestBed.configureTestingModule({ providers: [{ provide: ModelManagementService, useValue: {
      getBenchmarkDatasetMetadata: async () => ({ dataset: 'openai/gsm8k', subset: 'main', split: 'test',
        splits: [{ subset: 'main', split: 'test' }], text_columns: ['question'] }),
    } }] });
    const editor = TestBed.runInInjectionContext(() => new BenchmarkSettingsEditor());
    editor.setServing('tensor_parallel_size', '2');
    editor.setServing('gpu_memory_utilization', '0.8');
    editor.setServing('enable_prefix_caching', false);
    editor.setServing('kv_cache_memory_bytes', '4G');
    expect(editor.settings().serving_overrides).toEqual({ tensor_parallel_size: 2,
      gpu_memory_utilization: 0.8, enable_prefix_caching: false, kv_cache_memory_bytes: '4G' });
    editor.setServing('tensor_parallel_size', '');
    expect(editor.settings().serving_overrides['tensor_parallel_size']).toBeUndefined();
  });
});
