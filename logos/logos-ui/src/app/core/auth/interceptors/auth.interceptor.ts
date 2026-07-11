import { HttpInterceptorFn, HttpRequest } from '@angular/common/http';
import { inject } from '@angular/core';
import { from } from 'rxjs';
import { switchMap } from 'rxjs/operators';
import Keycloak from 'keycloak-js';
import { KEYCLOAK } from '../keycloak';

export const authInterceptor: HttpInterceptorFn = (req, next) => {
  // /info is public and fetched before login — never attach a bearer.
  if (req.url.endsWith('/info') || req.url.endsWith('/api/info')) {
    return next(req);
  }
  const kc = inject(KEYCLOAK);
  if (!kc.authenticated) {
    return next(req);
  }
  // Refresh-then-authorize as plain async; the only RxJS is the thin boundary
  // (`from` + `switchMap`) Angular requires — an interceptor must return an Observable.
  return from(authorize(kc, req)).pipe(switchMap((authorized) => next(authorized)));
};

/**
 * Refreshes the token if it expires within 30s, then returns the request with a
 * Bearer header. If the refresh fails the session is no longer valid: trigger a
 * Keycloak re-login redirect and let this in-flight request go un-bearered
 * (the page is navigating away) rather than attaching a stale token → silent 401.
 */
async function authorize(kc: Keycloak, req: HttpRequest<unknown>): Promise<HttpRequest<unknown>> {
  try {
    await kc.updateToken(30);
  } catch {
    void kc.login();
    return req;
  }
  const token = kc.token;
  return token ? req.clone({ setHeaders: { Authorization: `Bearer ${token}` } }) : req;
}
