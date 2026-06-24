import { Injectable, inject } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { firstValueFrom } from 'rxjs';

export interface BudgetBucket {
  team_id: number;
  team_name: string;
  bucket_ts: string;
  cost_micro_cents: number;
}

export interface TeamBudgetHistoryResponse {
  buckets: BudgetBucket[];
  bucket_seconds: number;
  start_iso: string;
  end_iso: string;
}

export interface KeyBudgetBucket {
  api_key_id: number;
  api_key_name: string;
  bucket_ts: string;
  cost_micro_cents: number;
}

export interface KeyBudgetHistoryResponse {
  buckets: KeyBudgetBucket[];
  bucket_seconds: number;
  start_iso: string;
  end_iso: string;
}

@Injectable({ providedIn: 'root' })
export class BillingService {
  private http = inject(HttpClient);

  getTeamBudgetHistory(startIso: string, endIso: string): Promise<TeamBudgetHistoryResponse> {
    return firstValueFrom(this.http.post<TeamBudgetHistoryResponse>('/api/logosdb/billing/team_budget_history', {
      start_iso: startIso,
      end_iso: endIso,
    }));
  }

  getKeyBudgetHistory(teamId: number, startIso: string, endIso: string): Promise<KeyBudgetHistoryResponse> {
    return firstValueFrom(this.http.post<KeyBudgetHistoryResponse>(`/api/logosdb/billing/key_budget_history/${teamId}`, {
      start_iso: startIso,
      end_iso: endIso,
    }));
  }
}
