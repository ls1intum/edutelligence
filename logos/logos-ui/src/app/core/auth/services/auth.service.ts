import { Injectable, signal, computed, inject } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { firstValueFrom } from 'rxjs';
import { User, UserRole } from '../models/user.model';

export type AuthStatus = 'checking' | 'authenticated' | 'unauthenticated';

const STORAGE_KEY = 'logos_api_key';

@Injectable({ providedIn: 'root' })
export class AuthService {
  private http = inject(HttpClient);

  apiKey      = signal<string>('');
  currentUser = signal<User | null>(null);
  status      = signal<AuthStatus>('checking');
  role        = computed<UserRole | null>(() => this.currentUser()?.role ?? null);

  constructor() {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (stored) {
      this.apiKey.set(stored);
      setTimeout(() => this.validateStoredKey(), 0);
    } else {
      this.status.set('unauthenticated');
    }
  }

  private async validateStoredKey(): Promise<void> {
    try {
      const user = await firstValueFrom(this.http.get<User>('/api/me'));
      this.currentUser.set(user);
      this.status.set('authenticated');
    } catch {
      localStorage.removeItem(STORAGE_KEY);
      this.apiKey.set('');
      this.status.set('unauthenticated');
    }
  }

  async login(key: string): Promise<boolean> {
    this.apiKey.set(key);
    try {
      const user = await firstValueFrom(this.http.get<User>('/api/me'));
      localStorage.setItem(STORAGE_KEY, key);
      this.currentUser.set(user);
      this.status.set('authenticated');
      return true;
    } catch {
      this.apiKey.set('');
      this.status.set('unauthenticated');
      return false;
    }
  }

  logout(): void {
    localStorage.removeItem(STORAGE_KEY);
    this.apiKey.set('');
    this.currentUser.set(null);
    this.status.set('unauthenticated');
  }
}
