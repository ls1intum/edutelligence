import { Injectable, inject } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { firstValueFrom } from 'rxjs';
import { Model, AddModelPayload, UpdateModelPayload } from '../../shared/models/model.model';
import { ProviderPerformanceResponse } from '../../shared/models/provider.model';

@Injectable({ providedIn: 'root' })
export class ModelManagementService {
  private http = inject(HttpClient);

  getModels(): Promise<Model[]> {
    return firstValueFrom(this.http.post<Model[]>('/api/logosdb/get_models', {}));
  }

  getPerformance(modelId: number): Promise<ProviderPerformanceResponse> {
    return firstValueFrom(
      this.http.post<ProviderPerformanceResponse>(
        '/api/logosdb/provider_performance',
        { model_id: modelId },
      ),
    );
  }

  /** Returns the id of the newly created model (the backend replies `{ model_id }`). */
  async addModel(payload: AddModelPayload): Promise<number> {
    const res = await firstValueFrom(
      this.http.post<{ model_id: number }>('/api/logosdb/add_model', payload),
    );
    return res.model_id;
  }

  /** The backend replies `{ result }` only; no model body is returned. */
  async updateModel(payload: UpdateModelPayload): Promise<void> {
    await firstValueFrom(this.http.post('/api/logosdb/update_model_info', payload));
  }

  deleteModel(id: number): Promise<void> {
    return firstValueFrom(this.http.post<void>('/api/logosdb/delete_model', { id }));
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
