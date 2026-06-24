import { Injectable, inject } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { firstValueFrom } from 'rxjs';
import { Policy, AddPolicyPayload, UpdatePolicyPayload } from '../../shared/models/policy.model';

@Injectable({ providedIn: 'root' })
export class PolicyService {
  private http = inject(HttpClient);

  getPolicies(): Promise<Policy[]> {
    return firstValueFrom(this.http.post<Policy[]>('/api/logosdb/get_policies', {}));
  }

  addPolicy(payload: AddPolicyPayload): Promise<Policy> {
    return firstValueFrom(this.http.post<Policy>('/api/logosdb/add_policy', payload));
  }

  updatePolicy(payload: UpdatePolicyPayload): Promise<Policy> {
    return firstValueFrom(this.http.post<Policy>('/api/logosdb/update_policy', payload));
  }

  deletePolicy(id: number): Promise<unknown> {
    return firstValueFrom(this.http.post<unknown>('/api/logosdb/delete_policy', { id }));
  }
}
