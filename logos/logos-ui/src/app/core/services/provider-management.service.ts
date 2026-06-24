import { Injectable, inject } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { firstValueFrom } from 'rxjs';
import {
  Provider,
  ModelConnection,
  AddProviderPayload,
  UpdateProviderPayload,
} from '../../shared/models/provider.model';

@Injectable({ providedIn: 'root' })
export class ProviderManagementService {
  private http = inject(HttpClient);

  getProviders(): Promise<Provider[]> {
    return firstValueFrom(this.http.post<Provider[]>('/api/logosdb/get_providers', {}));
  }

  addProvider(payload: AddProviderPayload): Promise<any> {
    return firstValueFrom(this.http.post<any>('/api/logosdb/add_provider', {
      provider_name:      payload.name,
      base_url:           payload.base_url,
      api_key:            payload.api_key ?? null,
      auth_name:          payload.auth_name ?? null,
      auth_format:        payload.auth_format ?? null,
      provider_type:      payload.provider_type,
      cloud_provider_type: payload.cloud_provider_type ?? null,
      privacy_level:      payload.privacy_level,
    }));
  }

  updateProvider(payload: UpdateProviderPayload): Promise<any> {
    return firstValueFrom(this.http.post<any>('/api/logosdb/update_provider', {
      provider_id:        payload.provider_id,
      provider_name:      payload.name ?? null,
      base_url:           payload.base_url ?? null,
      api_key:            payload.api_key ?? null,
      auth_name:          payload.auth_name ?? null,
      auth_format:        payload.auth_format ?? null,
      provider_type:      payload.provider_type ?? null,
      cloud_provider_type: payload.cloud_provider_type ?? null,
      privacy_level:      payload.privacy_level ?? null,
    }));
  }

  deleteProvider(id: number): Promise<void> {
    return firstValueFrom(this.http.post<void>('/api/logosdb/delete_provider', { provider_id: id }));
  }

  getProviderModels(providerId: number): Promise<ModelConnection[]> {
    return firstValueFrom(this.http.post<ModelConnection[]>('/api/logosdb/get_provider_models', { provider_id: providerId }));
  }

  connectModel(providerId: number, modelId: number, endpoint?: string, apiKey?: string): Promise<void> {
    return firstValueFrom(this.http.post<void>('/api/logosdb/connect_model_provider', {
      provider_id: providerId,
      model_id:    modelId,
      endpoint:    endpoint ?? null,
      api_key:     apiKey   ?? null,
    }));
  }

  disconnectModel(providerId: number, modelId: number): Promise<void> {
    return firstValueFrom(this.http.post<void>('/api/logosdb/disconnect_model_provider', {
      provider_id: providerId,
      model_id:    modelId,
    }));
  }
}
