import { Injectable, inject } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { firstValueFrom } from 'rxjs';
import { Model, AddModelPayload, UpdateModelPayload } from '../../shared/models/model.model';

@Injectable({ providedIn: 'root' })
export class ModelManagementService {
  private http = inject(HttpClient);

  getModels(): Promise<Model[]> {
    return firstValueFrom(this.http.post<Model[]>('/api/logosdb/get_models', {}));
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

  /**
   * Manually override the capability flags for a model. While `manual_override`
   * is set, the automatic LiteLLM catalog sync never touches the row again
   * (no overwrite on match, no delete on no-match). The backend replies with
   * the new state (`ModelCapabilityState`).
   */
  setModelCapabilities(
    modelId: number,
    supportsFunctionCalling: boolean,
    supportsVision: boolean,
    supportsReasoning: boolean,
  ): Promise<ModelCapabilityState> {
    return firstValueFrom(
      this.http.post<ModelCapabilityState>('/api/logosdb/set_model_capabilities', {
        model_id: modelId,
        supports_function_calling: supportsFunctionCalling,
        supports_vision: supportsVision,
        supports_reasoning: supportsReasoning,
      }),
    );
  }

  /**
   * Clear the manual override and re-sync the flags from the local catalog.
   * The backend replies with the re-synced state (`ModelCapabilityState`).
   */
  resetModelCapabilities(modelId: number): Promise<ModelCapabilityState> {
    return firstValueFrom(
      this.http.post<ModelCapabilityState>('/api/logosdb/reset_model_capabilities', {
        model_id: modelId,
      }),
    );
  }
}

export interface ModelCapability {
  id: number;
  model_id: number;
  supports_function_calling: boolean;
  supports_vision: boolean;
  supports_reasoning: boolean;
  manual_override: boolean;
}

/** State map returned by set/reset_model_capabilities. */
export interface ModelCapabilityState {
  model_id: number;
  supports_function_calling: boolean;
  supports_vision: boolean;
  supports_reasoning: boolean;
  manual_override: boolean;
}
