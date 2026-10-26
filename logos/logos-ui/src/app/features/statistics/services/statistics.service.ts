import { Injectable, inject } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { firstValueFrom } from 'rxjs';
import { RequestItem, VramV2Payload } from '../statistics.models';
import { RequestLatencyScope, RequestLatencyStats } from './request-latency.models';

/**
 * Lane-picker view of POST /api/logosdb/get_provider_models. The endpoint also
 * returns `endpoint`/`api_key` to Logos admins; both are deliberately left out
 * here so the credential never enters this feature's data flow.
 */
export interface ProviderModel {
  model_id: number;
  model_name: string;
}

/**
 * A lane an administrator locked warm, as `GET /api/logosdb/providers/logosnode/lanes/locks`
 * returns it. The capacity planner never sleeps, drains or unloads a locked lane.
 */
export interface LaneLock {
  provider_id: number;
  lane_id: string;
  model_name: string | null;
  locked_by: string | null;
  locked_at: string;
}

/**
 * A calibration that holds the maintenance slot. `claim_token` is null for a
 * session the worker reports without a claim; such a session can be stopped
 * but has no claim to release.
 */
export interface MaintenanceCalibration {
  provider_id: number;
  provider_name: string | null;
  claim_token: string | null;
  automatic: boolean | null;
  confirmed: boolean | null;
  since: string | null;
  age_s: number | null;
  online: boolean;
  calibrating: boolean;
  status_supported: boolean;
}

/**
 * A benchmark that holds the maintenance slot. While its cleanup still runs,
 * `status` is the job's final status, or null when the job record is gone.
 */
export interface MaintenanceBenchmark {
  job_id: number;
  status: string | null;
  provider_id: number | null;
  provider_name: string | null;
  model_name: string | null;
  nightly: boolean;
  since: string | null;
  age_s: number | null;
}

/** A nightly run whose worker settings are not restored yet. */
export interface MaintenanceRecovery {
  model_provider_id: number;
  status: string;
  provider_id: number | null;
  provider_name: string | null;
  model_name: string | null;
  since: string | null;
  age_s: number | null;
}

/** What holds the maintenance slot, as `GET /api/logosdb/maintenance` returns it. */
export interface MaintenanceStatus {
  limit: number;
  free: boolean;
  calibrations: MaintenanceCalibration[];
  benchmarks: MaintenanceBenchmark[];
  recoveries: MaintenanceRecovery[];
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

export interface RequestPayloads {
  input_payload: unknown;
  response_payload: unknown;
}

/** Narrowing of the request feed. `null` on a field means "do not narrow by it". */
export interface RequestFilter {
  userId: number | null;
  teamId: number | null;
  providerId: number | null;
  apiKeyId?: number | null;
  /** Keep only error/timeout outcomes when true. */
  errorsOnly: boolean;
  /** One lifecycle bucket (queued/running/error/finished), or null for all. */
  status: string | null;
  modelIds?: number[];
  providerIds?: number[];
}

/** One entry of a filter dropdown, with how much picking it would select. */
export interface ScopeOption {
  id: number;
  label: string;
  requestCount: number;
}

/** What the filter dropdowns should offer for the current range and scope. */
export interface ScopeOptions {
  teams: ScopeOption[];
  requesters: ScopeOption[];
  providers: ScopeOption[];
  models: ScopeOption[];
  apiKeys?: ScopeOption[];
}

@Injectable({ providedIn: 'root' })
export class StatisticsService {
  private http = inject(HttpClient);

  getRequestPayloads(requestId: string): Promise<RequestPayloads> {
    return firstValueFrom(this.http.post<RequestPayloads>('/api/logosdb/request_payloads', {
      request_id: requestId,
    }));
  }

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
  getScopeOptions(
    startIso: string,
    endIso: string,
    scope: {
      teamId: number | null;
      userId: number | null;
      providerId: number | null;
      apiKeyId?: number | null;
      errorsOnly: boolean;
    },
  ): Promise<ScopeOptions> {
    return firstValueFrom(this.http.post<ScopeOptions>('/api/logosdb/request_log_scope_options', {
      start_date: startIso,
      end_date: endIso,
      team_id: scope.teamId,
      user_id: scope.userId,
      provider_id: scope.providerId,
      api_key_id: scope.apiKeyId ?? null,
      errors_only: scope.errorsOnly || null,
    }));
  }

  // ── Cloud request delays ──────────────────────────────────────────────────

  /**
   * Delay percentiles of finished cloud requests inside `[startIso, endIso]`,
   * per model and provider, narrowed to the page scope.
   */
  getRequestLatencyStats(startIso: string, endIso: string, scope: RequestLatencyScope): Promise<RequestLatencyStats> {
    return firstValueFrom(this.http.post<RequestLatencyStats>('/api/logosdb/request_latency_stats', {
      start_date: startIso,
      end_date: endIso,
      team_id: scope.teamId,
      user_id: scope.userId,
      provider_id: scope.providerId,
      api_key_id: scope.apiKeyId,
      model_ids: scope.modelIds.length ? scope.modelIds : null,
    }));
  }

  // ── End cloud request delays ──────────────────────────────────────────────

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
        provider_id: filter.providerId,
        api_key_id: filter.apiKeyId ?? null,
        errors_only: filter.errorsOnly || null,
        status: filter.status,
        model_ids: filter.modelIds ?? [],
        provider_ids: filter.providerIds ?? [],
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

  /**
   * Recorded outcome of the most recent manual load of a model on a worker.
   *
   * `status` is `running | succeeded | failed | unknown`. `unknown` means the
   * orchestrator holds no recorded outcome (it restarted, or the entry aged
   * out) — callers must not render that as a failure.
   */
  getLaneLoadStatus(
    providerId: number,
    model: string,
  ): Promise<{ status?: string; reason?: string; lane_id?: string }> {
    return firstValueFrom(
      this.http.post<{ status?: string; reason?: string; lane_id?: string }>(
        '/api/logosdb/providers/logosnode/lanes/load_status',
        { provider_id: providerId, model }
      )
    );
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

  /**
   * Take a busy lane offline without dropping its in-flight requests. The
   * server marks the lane out of the rotation, waits for the in-flight
   * requests to finish, then sleeps the lane — or unloads it when the host
   * cannot hold a resident sleeper. The call can take as long as the last
   * request runs (plus the sleep), so the panel shows "Draining…" for the
   * whole ride. A lane that does not drain in time answers an error and
   * keeps serving, so the click can simply be retried.
   */
  drainLane(providerId: number, laneId: string): Promise<unknown> {
    return firstValueFrom(this.http.post<unknown>('/api/logosdb/providers/logosnode/lanes/drain', {
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

  /** Every lane lock across all providers. */
  getLaneLocks(): Promise<LaneLock[]> {
    return firstValueFrom(this.http.get<LaneLock[]>('/api/logosdb/providers/logosnode/lanes/locks'));
  }

  /** Lock a lane warm. Idempotent. */
  lockLane(providerId: number, laneId: string, modelName: string | null): Promise<LaneLock> {
    return firstValueFrom(this.http.post<LaneLock>('/api/logosdb/providers/logosnode/lanes/lock', {
      provider_id: providerId,
      lane_id: laneId,
      model_name: modelName,
    }));
  }

  /** Release a lane lock. Idempotent. */
  unlockLane(providerId: number, laneId: string): Promise<{ unlocked: boolean }> {
    return firstValueFrom(this.http.post<{ unlocked: boolean }>('/api/logosdb/providers/logosnode/lanes/unlock', {
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

  getMaintenanceStatus(): Promise<MaintenanceStatus> {
    return firstValueFrom(this.http.get<MaintenanceStatus>('/api/logosdb/maintenance'));
  }

  /**
   * Release a calibration claim. The server stops the calibration first and
   * refuses while the worker still reports a session.
   */
  releaseCalibrationClaim(
    providerId: number,
    claimToken: string,
  ): Promise<{ released: boolean; forced: boolean; message?: string }> {
    return firstValueFrom(this.http.post<{ released: boolean; forced: boolean; message?: string }>(
      '/api/logosdb/maintenance/release_calibration',
      { provider_id: providerId, claim_token: claimToken },
    ));
  }

  /**
   * Release a nightly recovery. Without `force` the server refuses (409) unless
   * the worker runs the lane's original settings.
   */
  releaseRecovery(
    modelProviderId: number,
    force: boolean,
  ): Promise<{ released: boolean; forced: boolean; message?: string }> {
    return firstValueFrom(this.http.post<{ released: boolean; forced: boolean; message?: string }>(
      '/api/logosdb/maintenance/release_recovery',
      { model_provider_id: modelProviderId, force },
    ));
  }

  stopCalibration(
    providerId: number
  ): Promise<{ was_active?: boolean; current_model?: string; error?: string }> {
    return firstValueFrom(this.http.post<{ was_active?: boolean; current_model?: string; error?: string }>(
      '/api/logosdb/providers/logosnode/stop_calibration',
      {
        provider_id: providerId,
      }
    ));
  }
}
