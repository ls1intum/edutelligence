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
  /** Desired number of lanes of this model on the node (1 = single lane). */
  replicas?: number;
}

/** Position to continue a request-feed page from, as the server hands it back. */
export interface RequestCursor {
  ts: string;
  request_id: string;
}

/** One page of the request feed, as `POST /api/logosdb/latest_requests` returns it. */
export interface LatestRequestsPage {
  requests: RequestItem[];
  total: number;
  limit: number;
  has_more: boolean;
  next_cursor: RequestCursor | null;
}

/** Narrowing of the request feed. `null` on a field means "do not narrow by it". */
export interface RequestFilter {
  userId: number | null;
  teamId: number | null;
}

/** One entry of a filter dropdown, with how much picking it would select. */
export interface ScopeOption {
  id: number;
  label: string;
  requestCount: number;
}

/** What the filter dropdowns should offer for the current range and team. */
export interface ScopeOptions {
  teams: ScopeOption[];
  requesters: ScopeOption[];
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
   * Teams and requesters worth offering in the filter for this range.
   *
   * Only what actually sent something, busiest first, and requesters narrowed to
   * `teamId` when one is selected — the platform's full user list is long,
   * unsearchable in a native select, and mostly made up of people who have never
   * sent a request.
   */
  getScopeOptions(startIso: string, endIso: string, teamId: number | null): Promise<ScopeOptions> {
    return firstValueFrom(this.http.post<ScopeOptions>('/api/logosdb/request_log_scope_options', {
      start_date: startIso,
      end_date: endIso,
      team_id: teamId,
    }));
  }

  /**
   * One page of the request feed inside `[startIso, endIso]`, newest first.
   *
   * The newest unfiltered rows arrive over the stats websocket; this serves
   * everything else — paging back through the range and any view narrowed to a
   * requester or team — so it is only ever called on an explicit interaction,
   * never on a timer.
   *
   * @param cursor `next_cursor` of the previous page, or null to start at the
   *               newest
   */
  getLatestRequests(
    startIso: string,
    endIso: string,
    limit: number,
    filter: RequestFilter,
    cursor: RequestCursor | null,
  ): Promise<LatestRequestsPage> {
    return firstValueFrom(
      this.http.post<LatestRequestsPage>('/api/logosdb/latest_requests', {
        start: startIso,
        end: endIso,
        limit,
        user_id: filter.userId,
        team_id: filter.teamId,
        cursor_ts: cursor?.ts ?? null,
        cursor_id: cursor?.request_id ?? null,
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

  /**
   * Put an awake lane to sleep. The server first drains in-flight requests
   * (mode="wait"), so the call can take as long as the drain — and rejects
   * with a reason only when the lane cannot sleep at all (its model is
   * configured without enable_sleep_mode). Sleep level 1 is fixed
   * server-side: the weights stay resident, so the wake below does not pay
   * for a cold load.
   */
  sleepLane(providerId: number, laneId: string): Promise<unknown> {
    return firstValueFrom(this.http.post<unknown>('/api/logosdb/providers/logosnode/lanes/sleep', {
      provider_id: providerId,
      lane_id: laneId,
    }));
  }

  wakeLane(providerId: number, laneId: string): Promise<unknown> {
    return firstValueFrom(this.http.post<unknown>('/api/logosdb/providers/logosnode/lanes/wake', {
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
