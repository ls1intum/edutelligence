import { Injectable, inject } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { firstValueFrom } from 'rxjs';

/** One of the caller's API keys. A batch runs as exactly one of them. */
export interface BatchKey {
  id: number;
  name: string;
  team_id: number | null;
  environment: string | null;
}

/** The OpenAI batch object, as Logos reports it for either execution path. */
export interface BatchObject {
  id: string;
  object: string;
  status: string;
  endpoint: string | null;
  input_file_id: string | null;
  output_file_id: string | null;
  created_at: number | null;
  completed_at: number | null;
  request_counts?: { total: number; completed: number; failed: number };
  /** 'logos' when Logos ran the job itself, 'provider' when it was forwarded. */
  logos_execution?: string;
}

/**
 * The batch page's data access.
 *
 * Everything goes through the webservice, which forwards to the orchestrator's
 * Batch API as the selected key — so the browser never handles a key value and
 * the permission and ownership rules are the ones every batch gets.
 */
@Injectable({ providedIn: 'root' })
export class BatchService {
  private http = inject(HttpClient);

  getKeys(): Promise<BatchKey[]> {
    return firstValueFrom(this.http.get<BatchKey[]>('/api/logosdb/batches/keys'));
  }

  list(apiKeyId: number): Promise<{ data: BatchObject[] }> {
    return firstValueFrom(
      this.http.get<{ data: BatchObject[] }>('/api/logosdb/batches', { params: { apiKeyId } }),
    );
  }

  get(apiKeyId: number, batchId: string): Promise<BatchObject> {
    return firstValueFrom(
      this.http.get<BatchObject>(`/api/logosdb/batches/${batchId}`, { params: { apiKeyId } }),
    );
  }

  cancel(apiKeyId: number, batchId: string): Promise<BatchObject> {
    return firstValueFrom(
      this.http.post<BatchObject>(`/api/logosdb/batches/${batchId}/cancel`, null, {
        params: { apiKeyId },
      }),
    );
  }

  create(
    apiKeyId: number,
    file: File,
    endpoint: string,
    execution: string,
  ): Promise<BatchObject> {
    const form = new FormData();
    form.append('file', file);
    form.append('apiKeyId', String(apiKeyId));
    form.append('endpoint', endpoint);
    form.append('execution', execution);
    return firstValueFrom(this.http.post<BatchObject>('/api/logosdb/batches', form));
  }

  /** The result file, as a blob the browser can save. */
  results(apiKeyId: number, batchId: string, outputFileId: string): Promise<Blob> {
    return firstValueFrom(
      this.http.get(`/api/logosdb/batches/${batchId}/results`, {
        params: { apiKeyId, outputFileId },
        responseType: 'blob',
      }),
    );
  }
}
