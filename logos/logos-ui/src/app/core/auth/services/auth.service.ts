import { Injectable, signal, computed, inject } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { firstValueFrom } from 'rxjs';
import { KeycloakTokenParsed } from 'keycloak-js';
import { KEYCLOAK } from '../keycloak';
import { PasskeyTokens } from '../passkey';
import { User, UserRole } from '../models/user.model';

export type AuthStatus = 'checking' | 'authenticated' | 'unauthenticated';

/** Decodes a JWT payload (no verification — keycloak-js needs `tokenParsed.exp`). */
function decodeJwt(token: string): KeycloakTokenParsed | undefined {
  try {
    const payload = token.split('.')[1];
    const json = atob(payload.replace(/-/g, '+').replace(/_/g, '/'));
    return JSON.parse(json) as KeycloakTokenParsed;
  } catch {
    return undefined;
  }
}

@Injectable({ providedIn: 'root' })
export class AuthService {
  private http = inject(HttpClient);
  readonly keycloak = inject(KEYCLOAK);

  currentUser = signal<User | null>(null);
  status      = signal<AuthStatus>('checking');
  role        = computed<UserRole | null>(() => this.currentUser()?.role ?? null);

  constructor() {
    // initKeycloak() (APP_INITIALIZER) has already run check-sso by now.
    if (this.keycloak.authenticated) {
      void this.refreshUser();
    } else {
      this.status.set('unauthenticated');
    }
  }

  accessToken(): string {
    return this.keycloak.token ?? '';
  }

  /**
   * Returns a token that is valid for at least the next 30s, refreshing if
   * needed. Returns '' if unauthenticated or the refresh fails (caller should
   * then not use a token — the next HTTP request's interceptor handles re-auth).
   */
  async freshToken(): Promise<string> {
    if (!this.keycloak.authenticated) return '';
    try {
      await this.keycloak.updateToken(30);
    } catch {
      return '';
    }
    return this.keycloak.token ?? '';
  }

  /** Loads /api/me with the current bearer token; sets auth state accordingly. */
  async refreshUser(): Promise<void> {
    try {
      const user = await firstValueFrom(this.http.get<User>('/api/me'));
      this.currentUser.set(user);
      this.status.set('authenticated');
    } catch {
      this.currentUser.set(null);
      this.status.set('unauthenticated');
    }
  }

  /** Redirects to Keycloak for an authorization-code (PKCE) login. */
  login(): void {
    void this.keycloak.login();
  }

  /**
   * Completes an in-page passkey login (mirrors the React app's `completeLogin`):
   * pushes the silently-obtained tokens into the keycloak-js instance so the
   * interceptor's `kc.token` and `updateToken()` refresh keep working, marks it
   * authenticated, then loads the user. No redirect.
   */
  async completeLogin(tokens: PasskeyTokens): Promise<void> {
    this.keycloak.token = tokens.accessToken;
    this.keycloak.refreshToken = tokens.refreshToken ?? undefined;
    this.keycloak.idToken = tokens.idToken ?? undefined;
    this.keycloak.tokenParsed = decodeJwt(tokens.accessToken);
    this.keycloak.refreshTokenParsed = tokens.refreshToken ? decodeJwt(tokens.refreshToken) : undefined;
    this.keycloak.idTokenParsed = tokens.idToken ? decodeJwt(tokens.idToken) : undefined;
    this.keycloak.authenticated = true;
    this.keycloak.timeSkew = 0;
    await this.refreshUser();
  }

  logout(): void {
    this.currentUser.set(null);
    this.status.set('unauthenticated');
    void this.keycloak.logout();
  }
}
