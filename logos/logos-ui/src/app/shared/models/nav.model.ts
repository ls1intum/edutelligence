import { UserRole } from '../../core/auth/models/user.model';

export type NavGroup = 'system' | 'management' | 'personal';

export interface MenuItem {
  label: string;
  path: string;
  piIcon: string;
  group: NavGroup;
  aliases?: string[];
  roles: UserRole[];
  /** Only shown when the agent runner is actually running on this deployment. */
  requiresAgent?: boolean;
  /** Only shown to the caller's own team members; logos_admin is exempt. */
  requiresTeam?: boolean;
}
