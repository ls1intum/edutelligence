import { inject, effect } from '@angular/core';
import { CanActivateFn, Router, UrlTree } from '@angular/router';
import { AuthService, AuthStatus } from '../services/auth.service';

export const adminGuard: CanActivateFn = () => {
  const auth   = inject(AuthService);
  const router = inject(Router);

  const decide = (status: AuthStatus): boolean | UrlTree => {
    if (status !== 'authenticated') return router.parseUrl('/');
    return auth.role() === 'logos_admin' ? true : router.parseUrl('/dashboard');
  };

  if (auth.status() !== 'checking') return decide(auth.status());

  return new Promise<boolean | UrlTree>(resolve => {
    const ref = effect(() => {
      const s = auth.status();
      if (s !== 'checking') {
        ref.destroy();
        resolve(decide(s));
      }
    });
  });
};
