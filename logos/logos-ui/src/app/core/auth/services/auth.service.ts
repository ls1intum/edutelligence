import { Injectable, signal, computed, inject } from '@angular/core';
import { HttpClient, HttpErrorResponse } from '@angular/common/http';
import { Observable, tap, catchError, of, map } from 'rxjs';
import { User, UserRole } from '../models/user.model';

export type AuthStatus = 'checking' | 'authenticated' | 'unauthenticated';

const STORAGE_KEY = 'logos_api_key';

@Injectable({ providedIn: 'root' })
export class AuthService {
  private http = inject(HttpClient);

  apiKey    = signal<string>('');
  currentUser = signal<User | null>(null);
  status    = signal<AuthStatus>('checking');
  role      = computed<UserRole | null>(() => this.currentUser()?.role ?? null);

  constructor() {
    const stored = localStorage.getItem(STORAGE_KEY);
    console.log('[AuthService] Constructor - stored key:', stored ? 'yes' : 'no');
    if (stored) {
      this.apiKey.set(stored);
      setTimeout(() => this.validateStoredKey(), 0);
    } else {
      this.status.set('unauthenticated');
    }
  }

  private validateStoredKey(): void {
    this.http.get<User>('/api/me').pipe(
      catchError((err) => {
        console.log('[AuthService] /api/me error:', err.status, err.message);
        localStorage.removeItem(STORAGE_KEY);
        this.apiKey.set('');
        this.status.set('unauthenticated');
        return of(null);
      }),
    ).subscribe(user => {
      console.log('[AuthService] /api/me response:', user ? 'authenticated' : 'not authenticated');
      if (user) {
        this.currentUser.set(user);
        this.status.set('authenticated');
      } else {
        this.status.set('unauthenticated');
      }
    });
  }

  login(key: string): Observable<boolean> {
    this.apiKey.set(key);
    return this.http.get<User>('/api/me').pipe(
      tap(user => {
        localStorage.setItem(STORAGE_KEY, key);
        this.currentUser.set(user);
        this.status.set('authenticated');
      }),
      map(() => true),
      catchError(() => {
        this.apiKey.set('');
        this.status.set('unauthenticated');
        return of(false);
      }),
    );
  }

  logout(): void {
    localStorage.removeItem(STORAGE_KEY);
    this.apiKey.set('');
    this.currentUser.set(null);
    this.status.set('unauthenticated');
  }
}
