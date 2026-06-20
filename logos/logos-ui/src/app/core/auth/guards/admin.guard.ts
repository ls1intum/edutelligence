import { inject } from '@angular/core';
import { CanActivateFn, Router } from '@angular/router';
import { toObservable } from '@angular/core/rxjs-interop';
import { filter, map, take } from 'rxjs';
import { AuthService } from '../services/auth.service';

export const adminGuard: CanActivateFn = () => {
  const auth   = inject(AuthService);
  const router = inject(Router);

  const decide = (status: string) => {
    if (status !== 'authenticated') return router.parseUrl('/');
    return auth.role() === 'logos_admin' ? true : router.parseUrl('/dashboard');
  };

  if (auth.status() !== 'checking') return decide(auth.status());

  return toObservable(auth.status).pipe(
    filter(s => s !== 'checking'),
    take(1),
    map(decide),
  );
};
