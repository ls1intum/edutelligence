import { MenuItem } from '../models/nav.model';
import { UserRole } from '../../core/auth/models/user.model';

const ALL_ROLES: UserRole[]       = ['logos_admin', 'app_admin', 'app_developer'];
const ADMIN_AND_ABOVE: UserRole[] = ['logos_admin', 'app_admin'];

export const MENU_ITEMS: MenuItem[] = [
  // System (logos_admin only)
  { label: 'Dashboard',  path: '/dashboard',       piIcon: 'th-large',       group: 'system',     roles: ['logos_admin'] },
  { label: 'Statistics', path: '/statistics',      piIcon: 'chart-bar',      group: 'system',     roles: ['logos_admin'] },
  { label: 'Models',     path: '/models',          piIcon: 'microchip-ai',   group: 'system',     roles: ALL_ROLES },
  { label: 'Providers',  path: '/providers',       piIcon: 'cloud',          group: 'system',     roles: ['logos_admin'] },
  { label: 'Policies',   path: '/policies',        piIcon: 'shield',         group: 'system',     roles: ['logos_admin'] },
  { label: 'Billing',    path: '/billing',         piIcon: 'credit-card',    group: 'system',     roles: ['logos_admin'] },
  { label: 'Agents',     path: '/agents',          piIcon: 'sparkles',       group: 'system',     roles: ['logos_admin'] },
  // Management (app_admin and above)
  { label: 'Users',      path: '/user-management', piIcon: 'users',          group: 'management', roles: ADMIN_AND_ABOVE },
  { label: 'Teams',      path: '/team-management', piIcon: 'sitemap',        group: 'management', roles: ADMIN_AND_ABOVE },
  // Personal (all roles)
  { label: 'My Workspace', path: '/my-workspace',  piIcon: 'objects-column', group: 'personal',   roles: ALL_ROLES },
  { label: 'AI Tools',    path: '/ai-tools',       piIcon: 'code',           group: 'personal',   roles: ALL_ROLES },
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
