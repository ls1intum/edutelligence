import { Injectable, inject } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import { MyKey, ModelAccess } from '../../shared/models/my-key.model';

@Injectable({ providedIn: 'root' })
export class MyKeysService {
  private http = inject(HttpClient);

  getMyKeys(): Observable<MyKey[]> {
    return this.http.get<MyKey[]>('/api/me/keys');
  }

  setLogLevel(keyId: number, log: 'BILLING' | 'FULL'): Observable<{ result: string }> {
    return this.http.patch<{ result: string }>(`/api/me/keys/${keyId}/log`, { log });
  }

  getKeyModels(keyId: number): Observable<ModelAccess[]> {
    return this.http.get<ModelAccess[]>(`/api/me/keys/${keyId}/models`);
  }
}
