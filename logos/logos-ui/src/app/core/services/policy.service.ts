import { Injectable, inject } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import { Policy, AddPolicyPayload, UpdatePolicyPayload } from '../../shared/models/policy.model';

@Injectable({ providedIn: 'root' })
export class PolicyService {
  private http = inject(HttpClient);

  getPolicies(): Observable<Policy[]> {
    return this.http.post<Policy[]>('/api/logosdb/get_policies', {});
  }

  addPolicy(payload: AddPolicyPayload): Observable<Policy> {
    return this.http.post<Policy>('/api/logosdb/add_policy', payload);
  }

  updatePolicy(payload: UpdatePolicyPayload): Observable<Policy> {
    return this.http.post<Policy>('/api/logosdb/update_policy', payload);
  }

  deletePolicy(id: number): Observable<unknown> {
    return this.http.post<unknown>('/api/logosdb/delete_policy', { id });
  }
}
