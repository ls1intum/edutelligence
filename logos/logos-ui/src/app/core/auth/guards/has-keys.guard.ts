import { inject } from '@angular/core';
import { CanActivateFn, Router, UrlTree } from '@angular/router';
import { MyKeysService } from '../../services/my-keys.service';
import { AuthService } from '../services/auth.service';
import { HOME_ROUTE } from '../../../shared/constants/nav-items';

/**
 * Requires both current team membership and an active key: keys outlive team
 * membership (an api_key row is keyed on user_id, not on the team_members
 * join), so a user removed from every team can still hold an orphaned active
 * key; team membership alone rules that case out.
 *
 * Fails closed: any fetch error is treated as "no keys", never as access.
 *
 * app_admin/logos_admin always have other pages to fall back to, so a lack of
 * access sends them home instead of to /no-access, which is reserved for
 * app_developer (whose only menu items are gated here).
 */
export const hasKeysGuard: CanActivateFn = async (): Promise<boolean | UrlTree> => {
  const keysService = inject(MyKeysService);
  const auth        = inject(AuthService);
  const router      = inject(Router);

  const hasTeams = (auth.currentUser()?.teams.length ?? 0) > 0;

  let hasKeys = false;
  try {
    hasKeys = (await keysService.getMyKeys()).length > 0;
  } catch {
    hasKeys = false;
  }

  if (hasTeams && hasKeys) return true;

  const role = auth.role();
  if (role && role !== 'app_developer') return router.parseUrl(HOME_ROUTE[role]);
  return router.parseUrl('/no-access');
};
