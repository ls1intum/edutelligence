import { MenuItem } from '../models/nav.model';
import { UserRole } from '../../core/auth/models/user.model';

const ALL_ROLES: UserRole[]       = ['logos_admin', 'app_admin', 'app_developer'];
const ADMIN_AND_ABOVE: UserRole[] = ['logos_admin', 'app_admin'];

export const MENU_ITEMS: MenuItem[] = [
  { label: 'Dashboard',    path: '/dashboard',       piIcon: 'home',        roles: ['logos_admin'] },
  { label: 'Statistics',   path: '/statistics',      piIcon: 'chart-bar',   roles: ['logos_admin'] },
  { label: 'Models',       path: '/models',          piIcon: 'microchip',   roles: ['logos_admin'] },
  { label: 'Providers',    path: '/providers',       piIcon: 'cloud',       roles: ['logos_admin'] },
  { label: 'Policies',     path: '/policies',        piIcon: 'shield',      roles: ['logos_admin'] },
  { label: 'Billing',      path: '/billing',         piIcon: 'credit-card', roles: ['logos_admin'] },

  { label: 'Users',        path: '/user-management', piIcon: 'users',       roles: ADMIN_AND_ABOVE },
  { label: 'Teams',        path: '/team-management', piIcon: 'sitemap',     roles: ADMIN_AND_ABOVE },

  { label: 'My Workspace', path: '/my-workspace',    piIcon: 'table',       roles: ALL_ROLES },
  { label: 'My Keys',      path: '/my-keys',         piIcon: 'key',         roles: ALL_ROLES },
  { label: 'OpenCode',     path: '/open-code',       piIcon: 'code',        roles: ALL_ROLES },
  { label: 'Settings',     path: '/settings',        piIcon: 'cog',         roles: ALL_ROLES },
];

export const HOME_ROUTE: Record<UserRole, string> = {
  logos_admin:   '/dashboard',
  app_admin:     '/user-management',
  app_developer: '/my-workspace',
};
