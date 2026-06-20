import { Injectable, inject } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import { VramV2Payload, PaginatedRequestResponse } from '../statistics.models';

@Injectable({ providedIn: 'root' })
export class StatisticsService {
  private http = inject(HttpClient);

  getVramStats(day: string): Observable<VramV2Payload> {
    return this.http.post<VramV2Payload>('/api/logosdb/get_ollama_vram_stats', {
      day,
    });
  }

  getPaginatedRequests(page: number, perPage: number): Observable<PaginatedRequestResponse> {
    return this.http.post<PaginatedRequestResponse>('/api/logosdb/paginated_requests', {
      page,
      per_page: perPage,
    });
  }

  unloadLane(providerId: number, laneId: string): Observable<unknown> {
    return this.http.post<unknown>('/api/logosdb/providers/logosnode/lanes/delete', {
      provider_id: providerId,
      lane_id: laneId,
    });
  }

  calibrateUncalibrated(providerId: number): Observable<{ count?: number; models?: string[]; error?: string }> {
    return this.http.post<{ count?: number; models?: string[]; error?: string }>(
      '/api/logosdb/providers/logosnode/calibrate_uncalibrated',
      {
        provider_id: providerId,
      }
    );
  }
}
