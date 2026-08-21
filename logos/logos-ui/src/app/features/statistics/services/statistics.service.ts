import { Injectable, inject } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { firstValueFrom } from 'rxjs';
import { VramV2Payload } from '../statistics.models';

/**
 * Lane-picker view of POST /api/logosdb/get_provider_models. The endpoint also
 * returns `endpoint`/`api_key`; both are deliberately left out here so the
 * credential never enters this feature's data flow.
 */
export interface ProviderModel {
  model_id: number;
  model_name: string;
}

@Injectable({ providedIn: 'root' })
export class StatisticsService {
  private http = inject(HttpClient);

  getVramStats(day: string): Promise<VramV2Payload> {
    return firstValueFrom(this.http.post<VramV2Payload>('/api/logosdb/get_ollama_vram_stats', {
      day,
    }));
  }

  /** Models registered on a provider (for the "Load lane" picker). */
  getProviderModels(providerId: number): Promise<ProviderModel[]> {
    return firstValueFrom(this.http.post<ProviderModel[]>('/api/logosdb/get_provider_models', {
      provider_id: providerId,
    }));
  }

  /**
   * Manually load a single lane (model) on a worker. The worker loads the
   * model, which can take minutes — the call simply waits for the server
   * (Spring gives the orchestrator call a ~185 s budget).
   */
  addLane(providerId: number, model: string): Promise<unknown> {
    return firstValueFrom(this.http.post<unknown>('/api/logosdb/providers/logosnode/lanes/add', {
      provider_id: providerId,
      lane: { model },
    }));
  }

  unloadLane(providerId: number, laneId: string): Promise<unknown> {
    return firstValueFrom(this.http.post<unknown>('/api/logosdb/providers/logosnode/lanes/delete', {
      provider_id: providerId,
      lane_id: laneId,
    }));
  }

  calibrateUncalibrated(providerId: number): Promise<{ count?: number; models?: string[]; error?: string }> {
    return firstValueFrom(this.http.post<{ count?: number; models?: string[]; error?: string }>(
      '/api/logosdb/providers/logosnode/calibrate_uncalibrated',
      {
        provider_id: providerId,
      }
    ));
  }
}
