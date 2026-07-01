import { MenuItem } from '../models/nav.model';
import { UserRole } from '../../core/auth/models/user.model';

const ALL_ROLES: UserRole[]       = ['logos_admin', 'app_admin', 'app_developer'];
const ADMIN_AND_ABOVE: UserRole[] = ['logos_admin', 'app_admin'];

export const MENU_ITEMS: MenuItem[] = [
  // System (logos_admin only)
  { label: 'Dashboard',  path: '/dashboard',       piIcon: 'th-large',       accentColor: 'cyan',   group: 'system',     roles: ['logos_admin'] },
  { label: 'Statistics', path: '/statistics',      piIcon: 'chart-bar',      accentColor: 'green',  group: 'system',     roles: ['logos_admin'] },
  { label: 'Models',     path: '/models',          piIcon: 'microchip-ai',   accentColor: 'orange', group: 'system',     roles: ['logos_admin'] },
  { label: 'Providers',  path: '/providers',       piIcon: 'cloud',          accentColor: 'pink',   group: 'system',     roles: ['logos_admin'] },
  { label: 'Policies',   path: '/policies',        piIcon: 'shield',         accentColor: 'yellow', group: 'system',     roles: ['logos_admin'] },
  { label: 'Billing',    path: '/billing',         piIcon: 'credit-card',    accentColor: 'purple', group: 'system',     roles: ['logos_admin'] },
  // Management (app_admin and above)
  { label: 'Users',      path: '/user-management', piIcon: 'users',          accentColor: 'cyan',   group: 'management', roles: ADMIN_AND_ABOVE },
  { label: 'Teams',      path: '/team-management', piIcon: 'sitemap',        accentColor: 'green',  group: 'management', roles: ADMIN_AND_ABOVE },
  // Personal (all roles)
  { label: 'My Workspace', path: '/my-workspace',  piIcon: 'objects-column', accentColor: 'green',  group: 'personal',   roles: ALL_ROLES },
  { label: 'OpenCode',   path: '/open-code',       piIcon: 'code',           accentColor: 'yellow', group: 'personal',   roles: ALL_ROLES },
];

export const HOME_ROUTE: Record<UserRole, string> = {
  logos_admin:   '/dashboard',
  app_admin:     '/user-management',
  app_developer: '/my-workspace',
};

export const NAV_GROUP_LABELS: Record<string, string> = {
  system:     'SYSTEM',
  management: 'MANAGEMENT',
  personal:   'PERSONAL',
};
