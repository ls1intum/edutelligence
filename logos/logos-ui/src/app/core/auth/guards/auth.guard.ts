import { inject } from '@angular/core';
import { CanActivateFn, Router } from '@angular/router';
import { toObservable } from '@angular/core/rxjs-interop';
import { filter, map, take } from 'rxjs';
import { AuthService } from '../services/auth.service';

export const authGuard: CanActivateFn = () => {
  const auth   = inject(AuthService);
  const router = inject(Router);

  const decide = (s: string) => s === 'authenticated' ? true : router.parseUrl('/');

  if (auth.status() !== 'checking') return decide(auth.status());

  return toObservable(auth.status).pipe(
    filter(s => s !== 'checking'),
    take(1),
    map(decide),
  );
};
