import { inject, effect } from '@angular/core';
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
 * Reads MyKeysService.hasKeys — the same signal the Shell sidebar uses —
 * instead of independently re-fetching /api/me/keys on every navigation.
 * That signal only refreshes on team-membership change (join/leave flips key
 * state server-side), so a key revoked without a membership change won't
 * block this route until the next membership change re-resolves it; the
 * actual data endpoints still enforce ownership server-side regardless, so
 * this only affects how quickly the route stops being reachable, not real
 * access to data.
 *
 * Fails closed: an unresolved/errored signal is treated as "no keys", never
 * as access.
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

  let resolved = keysService.hasKeys();
  if (resolved === null) {
    resolved = await new Promise<boolean>((resolve) => {
      const ref = effect(() => {
        const v = keysService.hasKeys();
        if (v !== null) {
          ref.destroy();
          resolve(v);
        }
      });
    });
  }

  if (hasTeams && resolved) return true;

  const role = auth.role();
  if (role && role !== 'app_developer') return router.parseUrl(HOME_ROUTE[role]);
  return router.parseUrl('/no-access');
};
