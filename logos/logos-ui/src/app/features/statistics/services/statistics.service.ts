import { Injectable, inject } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { firstValueFrom } from 'rxjs';
import { RequestItem, VramV2Payload } from '../statistics.models';

/**
 * Lane-picker view of POST /api/logosdb/get_provider_models. The endpoint also
 * returns `endpoint`/`api_key`; both are deliberately left out here so the
 * credential never enters this feature's data flow.
 */
export interface ProviderModel {
  model_id: number;
  model_name: string;
}

/** One page of the request feed, as `POST /api/logosdb/latest_requests` returns it. */
export interface LatestRequestsPage {
  requests: RequestItem[];
  total: number;
  offset: number;
  limit: number;
  has_more: boolean;
}

@Injectable({ providedIn: 'root' })
export class StatisticsService {
  private http = inject(HttpClient);

  getVramStats(day: string): Promise<VramV2Payload> {
    return firstValueFrom(this.http.post<VramV2Payload>('/api/logosdb/get_ollama_vram_stats', {
      day,
    }));
  }

  /**
   * One page of the request feed inside `[startIso, endIso]`, newest first.
   *
   * The live rows arrive over the stats websocket; this exists for the operator
   * walking backwards through the range, which is why it is only ever called on
   * an explicit "load older" and never on a timer.
   */
  getLatestRequests(
    startIso: string,
    endIso: string,
    limit: number,
    offset: number,
  ): Promise<LatestRequestsPage> {
    return firstValueFrom(
      this.http.post<LatestRequestsPage>('/api/logosdb/latest_requests', {
        start: startIso,
        end: endIso,
        limit,
        offset,
      }),
    );
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
