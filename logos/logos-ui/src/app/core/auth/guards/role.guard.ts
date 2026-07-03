import { inject, effect } from '@angular/core';
import { ActivatedRouteSnapshot, CanActivateFn, Router, UrlTree } from '@angular/router';
import { AuthService, AuthStatus } from '../services/auth.service';
import { HOME_ROUTE } from '../../../shared/constants/nav-items';
import { UserRole } from '../models/user.model';

export const roleGuard: CanActivateFn = (route: ActivatedRouteSnapshot) => {
  const auth         = inject(AuthService);
  const router       = inject(Router);
  const allowedRoles = route.data['roles'] as UserRole[];

  const decide = (status: AuthStatus): boolean | UrlTree => {
    if (status !== 'authenticated') return router.parseUrl('/');
    const role = auth.role();
    if (!role) return router.parseUrl('/');
    if (allowedRoles.includes(role)) return true;
    return router.parseUrl(HOME_ROUTE[role]);
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
