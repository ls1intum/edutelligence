import { Injectable, inject } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { firstValueFrom } from 'rxjs';
import { MyKey, ModelAccess } from '../../shared/models/my-key.model';

@Injectable({ providedIn: 'root' })
export class MyKeysService {
  private http = inject(HttpClient);

  getMyKeys(): Promise<MyKey[]> {
    return firstValueFrom(this.http.get<MyKey[]>('/api/me/keys'));
  }

  setLogLevel(keyId: number, log: 'BILLING' | 'FULL'): Promise<{ result: string }> {
    return firstValueFrom(this.http.patch<{ result: string }>(`/api/me/keys/${keyId}/log`, { log }));
  }

  getKeyModels(keyId: number): Promise<ModelAccess[]> {
    return firstValueFrom(this.http.get<ModelAccess[]>(`/api/me/keys/${keyId}/models`));
  }
}
