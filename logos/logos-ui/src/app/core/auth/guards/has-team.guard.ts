import { inject } from '@angular/core';
import { CanActivateFn, Router, UrlTree } from '@angular/router';
import { AuthService } from '../services/auth.service';
import { HOME_ROUTE } from '../../../shared/constants/nav-items';

/**
 * Requires current team membership — a teamless caller has no models to
 * request or vote on. logos_admin is exempt: the catalog is what they manage.
 *
 * Unlike hasKeysGuard, an active key is not required: a team member without a
 * key still sees the model catalogue and can vote on model requests.
 *
 * The fallback mirrors hasKeysGuard: admins have other pages to land on, so
 * they go home; an app_developer — whose remaining menu items are all
 * team-gated — goes to /no-access.
 */
export const hasTeamGuard: CanActivateFn = (): boolean | UrlTree => {
  const auth = inject(AuthService);
  const router = inject(Router);

  const role = auth.role();
  const hasTeams = (auth.currentUser()?.teams.length ?? 0) > 0;
  if (role === 'logos_admin' || hasTeams) return true;

  if (role && role !== 'app_developer') return router.parseUrl(HOME_ROUTE[role]);
  return router.parseUrl('/no-access');
};
