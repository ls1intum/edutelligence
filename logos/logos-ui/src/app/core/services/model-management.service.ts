import { BenchmarkBatch } from '../../features/model-error-report/benchmark-batch';
import { Injectable, inject } from '@angular/core';
import { BenchmarkSettings, BenchmarkWorkerLimits, DatasetMetadata, DEFAULT_BENCHMARK_SETTINGS } from '../../features/model-error-report/benchmark-settings';
import { HttpClient } from '@angular/common/http';
import { firstValueFrom } from 'rxjs';
import { Model, AddModelPayload, UpdateModelPayload } from '../../shared/models/model.model';
import { ModelBenchmarkResponse, StartModelBenchmarkResponse } from '../../shared/models/provider.model';
import { ModelAccessResponse } from '../../shared/models/model-access.model';
import { ModelPriceResponse } from '../../shared/models/model-price.model';

@Injectable({ providedIn: 'root' })
export class ModelManagementService {
  private http = inject(HttpClient);

  getModels(): Promise<Model[]> {
    return firstValueFrom(this.http.post<Model[]>('/api/logosdb/get_models', {}));
  }

  /**
   * Current and historic catalogue prices for one model, grouped per
   * linked provider. Only logos admins may read it (model details page).
   */
  getModelPrices(modelId: number): Promise<ModelPriceResponse> {
    return firstValueFrom(
      this.http.post<ModelPriceResponse>(
        '/api/logosdb/get_model_prices',
        { id: modelId },
      ),
    );
  }

  getBenchmarks(modelId: number): Promise<ModelBenchmarkResponse> {
    return firstValueFrom(
      this.http.post<ModelBenchmarkResponse>(
        '/api/logosdb/model_benchmarks',
        { model_id: modelId },
      ),
    );
  }

  startBenchmark(modelProviderId: number, sampleSize: number, settings: BenchmarkSettings = DEFAULT_BENCHMARK_SETTINGS, batch?: BenchmarkBatch): Promise<StartModelBenchmarkResponse> {
    return firstValueFrom(
      this.http.post<StartModelBenchmarkResponse>(
        '/api/logosdb/model_benchmarks/run',
        {
          model_provider_id: modelProviderId,
          sample_size: sampleSize,
          ...settings,
          ...(batch ? { batch } : {}),
        },
      ),
    );
  }

  getBenchmarkWorkerLimits(modelProviderId: number): Promise<BenchmarkWorkerLimits> {
    return firstValueFrom(this.http.post<BenchmarkWorkerLimits>(
      '/api/logosdb/model_benchmarks/limits', { model_provider_id: modelProviderId },
    ));
  }

  searchBenchmarkDatasets(query: string, cursor?: string): Promise<{ datasets: { id: string }[]; next_cursor?: string | null }> {
    return firstValueFrom(this.http.post<{ datasets: { id: string }[]; next_cursor?: string | null }>(
      '/api/logosdb/model_benchmarks/datasets/search', { query, ...(cursor ? { cursor } : {}) },
    ));
  }

  getBenchmarkDatasetMetadata(dataset: string, subset?: string, split?: string): Promise<DatasetMetadata> {
    return firstValueFrom(this.http.post<DatasetMetadata>(
      '/api/logosdb/model_benchmarks/datasets/metadata', { dataset, subset, split },
    ));
  }

  cancelBenchmark(jobId: number): Promise<{ job_id: number; status: string }> {
    return firstValueFrom(
      this.http.post<{ job_id: number; status: string }>(
        '/api/logosdb/model_benchmarks/cancel',
        { id: jobId },
      ),
    );
  }

  deleteBenchmark(benchmarkId: number): Promise<{ deleted: boolean; id: number }> {
    return firstValueFrom(
      this.http.post<{ deleted: boolean; id: number }>(
        '/api/logosdb/model_benchmarks/delete',
        { id: benchmarkId },
      ),
    );
  }

  /** Returns the id of the newly created model (the application server replies `{ model_id }`). */
  async addModel(payload: AddModelPayload): Promise<number> {
    const res = await firstValueFrom(
      this.http.post<{ model_id: number }>('/api/logosdb/add_model', payload),
    );
    return res.model_id;
  }

  /** the application server replies `{ result }` only; no model body is returned. */
  async updateModel(payload: UpdateModelPayload): Promise<void> {
    await firstValueFrom(this.http.post('/api/logosdb/update_model_info', payload));
  }

  deleteModel(id: number): Promise<void> {
    return firstValueFrom(this.http.post<void>('/api/logosdb/delete_model', { id }));
  }
  /** Admin-only access matrix: hosting providers, team grants, custom-permission keys. */
  getModelAccess(modelId: number): Promise<ModelAccessResponse> {
    return firstValueFrom(
      this.http.get<ModelAccessResponse>(`/api/admin/models/${modelId}/access`),
    );
  }

  async getModelCapabilities(modelIds: number[]): Promise<Record<number, ModelCapability>> {
    return firstValueFrom(
      this.http.post<Record<number, ModelCapability>>(
        '/api/logosdb/get_model_capabilities',
        { ids: modelIds },
      ),
    );
  }
}

export interface ModelCapability {
  id: number;
  model_id: number;
  supports_function_calling: boolean;
  supports_vision: boolean;
  supports_reasoning: boolean;
}
