import { Injectable, inject, signal, computed, effect } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { firstValueFrom } from 'rxjs';
import { MyKey, ModelAccess } from '../../shared/models/my-key.model';
import { AuthService } from '../auth/services/auth.service';

@Injectable({ providedIn: 'root' })
export class MyKeysService {
  private http = inject(HttpClient);
  private auth = inject(AuthService);

  /**
   * hasKeysGuard fetches keys to decide route access, then the page component
   * (my-workspace/open-code) fetches the same list again in ngOnInit right
   * after — two sequential round trips per navigation for data that can't
   * have changed between them. Short TTL avoids the duplicate without
   * meaningfully staling the access check.
   */
  private static readonly CACHE_TTL_MS = 5_000;
  private cachedKeys: MyKey[] | null = null;
  private cachedAtMs = 0;
  /**
   * hasKeysGuard (via the shared hasKeys signal) and the page's own ngOnInit
   * both call getMyKeys() within milliseconds of each other on a fresh
   * navigation. The TTL check above only dedupes against an already-resolved
   * value, so two calls issued before the first responds would otherwise both
   * hit the network. Sharing the in-flight promise closes that gap regardless
   * of how long the request takes.
   */
  private keysInFlight: Promise<MyKey[]> | null = null;
  /**
   * Bumped by invalidateCache() so a request started before the invalidation
   * can't write its (pre-mutation) result back into the cache after the fact
   * -- without this, a still-in-flight promise reused by the code below would
   * both be returned to the membership-change effect AND repopulate the
   * cache with stale data once it resolved.
   */
  private keysGeneration = 0;

  getMyKeys(): Promise<MyKey[]> {
    if (this.cachedKeys && Date.now() - this.cachedAtMs < MyKeysService.CACHE_TTL_MS) {
      return Promise.resolve(this.cachedKeys);
    }
    if (this.keysInFlight) return this.keysInFlight;
    const generation = this.keysGeneration;
    const request: Promise<MyKey[]> = firstValueFrom(this.http.get<MyKey[]>('/api/me/keys'))
      .then((keys) => {
        if (generation === this.keysGeneration) {
          this.cachedKeys = keys;
          this.cachedAtMs = Date.now();
        }
        return keys;
      })
      .finally(() => {
        if (this.keysInFlight === request) this.keysInFlight = null;
      });
    this.keysInFlight = request;
    return request;
  }

  /**
   * The membership-change effect below must always see the post-mutation
   * state, not a pre-mutation value still within the TTL window above. That
   * means discarding any in-flight request too -- otherwise getMyKeys()
   * would hand back a promise for a fetch that started before the mutation.
   */
  invalidateCache(): void {
    this.keysGeneration++;
    this.cachedKeys = null;
    this.keysInFlight = null;
  }

  setLogLevel(keyId: number, log: 'BILLING' | 'FULL'): Promise<{ result: string }> {
    this.invalidateCache();
    return firstValueFrom(this.http.patch<{ result: string }>(`/api/me/keys/${keyId}/log`, { log }));
  }

  rotateKey(keyId: number): Promise<{ result: string; api_key: string }> {
    this.invalidateCache();
    return firstValueFrom(
      this.http.post<{ result: string; api_key: string }>(`/api/me/keys/${keyId}/rotate`, {}),
    );
  }

  /**
   * OpenCode fetches the default key's models on every navigation (it can't
   * be parallelized with getMyKeys() above -- it needs the key id from that
   * call's result), so a quick back-and-forth between pages repeats the same
   * models request. Same TTL/in-flight-sharing pattern as getMyKeys(), keyed
   * per key id; a failed request is never cached, so retryModels() (my
   * workspace) still forces a fresh fetch.
   */
  private modelsCache = new Map<number, { models: ModelAccess[]; atMs: number }>();
  private modelsInFlight = new Map<number, Promise<ModelAccess[]>>();

  getKeyModels(keyId: number): Promise<ModelAccess[]> {
    const cached = this.modelsCache.get(keyId);
    if (cached && Date.now() - cached.atMs < MyKeysService.CACHE_TTL_MS) {
      return Promise.resolve(cached.models);
    }
    const inFlight = this.modelsInFlight.get(keyId);
    if (inFlight) return inFlight;
    const request = firstValueFrom(this.http.get<ModelAccess[]>(`/api/me/keys/${keyId}/models`))
      .then((models) => {
        this.modelsCache.set(keyId, { models, atMs: Date.now() });
        return models;
      })
      .finally(() => {
        this.modelsInFlight.delete(keyId);
      });
    this.modelsInFlight.set(keyId, request);
    return request;
  }

  // ── Shared "does this user have an active key" state ──────────────────────
  // Single source of truth for both the sidebar nav (Shell) and hasKeysGuard,
  // so navigating between my-workspace/open-code reads an already-resolved
  // signal instead of paying a fresh network round trip on every click. Only
  // re-fetches when team membership changes (join/leave flips key state
  // server-side), same trigger as before this was shared.

  /** null while unresolved (or logged out); treated as hidden/blocked until proven. */
  hasKeys = signal<boolean | null>(null);

  /**
   * String fingerprint of the current user's team ids (null when logged out).
   * A string keeps the computed referentially stable across refreshUser()
   * calls that don't change membership, so the effect below only fires on
   * actual membership changes.
   */
  private teamFingerprint = computed(() => {
    const user = this.auth.currentUser();
    if (!user) return null;
    return user.teams.map((t) => t.id).sort((a, b) => a - b).join(',');
  });

  /** Discards responses of superseded key fetches (see effect below). */
  private hasKeysFetchGeneration = 0;

  constructor() {
    // Joining a team auto-creates a developer key server-side (and leaving
    // deactivates it), so a membership change is exactly when key state can
    // flip; re-fetch instead of guessing.
    effect(() => {
      const fingerprint = this.teamFingerprint();
      const generation = ++this.hasKeysFetchGeneration;
      this.hasKeys.set(null);
      if (fingerprint === null) return;
      // A membership change is exactly when the backend may have just
      // created/deactivated a key, so this bypasses the short TTL cache
      // above rather than risk a pre-mutation value.
      this.invalidateCache();
      this.getMyKeys()
        .then((keys) => {
          if (generation === this.hasKeysFetchGeneration) this.hasKeys.set(keys.length > 0);
        })
        .catch(() => {
          if (generation === this.hasKeysFetchGeneration) this.hasKeys.set(false);
        });
    });
  }
}
