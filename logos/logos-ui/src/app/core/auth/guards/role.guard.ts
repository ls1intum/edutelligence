import { inject } from '@angular/core';
import { ActivatedRouteSnapshot, CanActivateFn, Router } from '@angular/router';
import { toObservable } from '@angular/core/rxjs-interop';
import { filter, map, take } from 'rxjs';
import { AuthService } from '../services/auth.service';
import { HOME_ROUTE } from '../../../shared/constants/nav-items';
import { UserRole } from '../models/user.model';

export const roleGuard: CanActivateFn = (route: ActivatedRouteSnapshot) => {
  const auth         = inject(AuthService);
  const router       = inject(Router);
  const allowedRoles = route.data['roles'] as UserRole[];

  const decide = (status: string) => {
    if (status !== 'authenticated') return router.parseUrl('/');
    const role = auth.role();
    if (!role) return router.parseUrl('/');
    if (allowedRoles.includes(role)) return true;
    return router.parseUrl(HOME_ROUTE[role]);
  };

  if (auth.status() !== 'checking') return decide(auth.status());

  return toObservable(auth.status).pipe(
    filter(s => s !== 'checking'),
    take(1),
    map(decide),
  );
};
