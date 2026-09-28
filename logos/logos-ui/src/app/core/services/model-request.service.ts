import { Injectable, inject } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { firstValueFrom } from 'rxjs';

/**
 * One requested model, as the webservice reports it: the registry row id, the
 * model name, how many users have voted for it, and whether the caller has.
 * The keys mirror the columns of the `requested_models` / `requested_model_votes`
 * tables (the webservice serializes in snake_case).
 */
export interface ModelRequest {
  id: number;
  name: string;
  request_count: number;
  has_voted: boolean;
}

/**
 * Data access for the model-request voting section (embedded in the Models
 * page).
 *
 * A model request is a vote for a model Logos does not serve yet — a demand
 * signal, not a configuration change. Each user gets one vote per model; they
 * can take it back (undo) and cast it again. The listing shows what everyone
 * has voted for, with the caller's own vote state.
 */
@Injectable({ providedIn: 'root' })
export class ModelRequestService {
  private http = inject(HttpClient);

  list(): Promise<ModelRequest[]> {
    return firstValueFrom(this.http.post<ModelRequest[]>('/api/logosdb/get_model_requests', {}));
  }

  /** Cast the caller's vote for a model (a no-op if they already voted). */
  vote(name: string): Promise<ModelRequest> {
    return firstValueFrom(this.http.post<ModelRequest>('/api/logosdb/add_model_request', { name }));
  }

  /** Take the caller's vote back for a model (idempotent). */
  undoVote(name: string): Promise<ModelRequest> {
    return firstValueFrom(
      this.http.post<ModelRequest>('/api/logosdb/remove_model_request', { name }),
    );
  }
}
