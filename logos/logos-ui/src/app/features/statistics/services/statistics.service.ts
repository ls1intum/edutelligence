import { Injectable, inject } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { firstValueFrom } from 'rxjs';
import { VramV2Payload, PaginatedRequestResponse } from '../statistics.models';

@Injectable({ providedIn: 'root' })
export class StatisticsService {
  private http = inject(HttpClient);

  getVramStats(day: string): Promise<VramV2Payload> {
    return firstValueFrom(this.http.post<VramV2Payload>('/api/logosdb/get_ollama_vram_stats', {
      day,
    }));
  }

  getPaginatedRequests(page: number, perPage: number): Promise<PaginatedRequestResponse> {
    return firstValueFrom(this.http.post<PaginatedRequestResponse>('/api/logosdb/paginated_requests', {
      page,
      per_page: perPage,
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
