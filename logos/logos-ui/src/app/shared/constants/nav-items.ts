import { MenuItem } from '../models/nav.model';
import { UserRole } from '../../core/auth/models/user.model';

const ALL_ROLES: UserRole[]       = ['logos_admin', 'app_admin', 'app_developer'];
const ADMIN_AND_ABOVE: UserRole[] = ['logos_admin', 'app_admin'];

export const MENU_ITEMS: MenuItem[] = [
  // ── System (logos_admin only) ─────────────────────────────────────────────
  { label: 'Dashboard',    path: '/dashboard',       piIcon: 'th-large',       iconColor: 'rgb(var(--color-icon-cyan))', iconOpacity: '12%', group: 'system',     roles: ['logos_admin'] },
  { label: 'Statistics',   path: '/statistics',      piIcon: 'chart-bar',      iconColor: 'rgb(var(--color-icon-green))', iconOpacity: '12%', group: 'system',     roles: ['logos_admin'] },
  { label: 'Models',       path: '/models',          piIcon: 'microchip-ai',   iconColor: 'rgb(var(--color-icon-orange))', iconOpacity: '12%', group: 'system',     roles: ['logos_admin'] },
  { label: 'Providers',    path: '/providers',       piIcon: 'cloud',          iconColor: 'rgb(var(--color-icon-pink))', iconOpacity: '12%', group: 'system',     roles: ['logos_admin'] },
  { label: 'Policies',     path: '/policies',        piIcon: 'shield',         iconColor: 'rgb(var(--color-icon-yellow))', iconOpacity: '12%', group: 'system',     roles: ['logos_admin'] },
  { label: 'Billing',      path: '/billing',         piIcon: 'credit-card',    iconColor: 'rgb(var(--color-icon-purple))', iconOpacity: '12%', group: 'system',     roles: ['logos_admin'] },
  // ── Management (app_admin and above) ──────────────────────────────────────
  { label: 'Users',        path: '/user-management', piIcon: 'users',          iconColor: 'rgb(var(--color-icon-cyan))', iconOpacity: '12%', group: 'management', roles: ADMIN_AND_ABOVE },
  { label: 'Teams',        path: '/team-management', piIcon: 'sitemap',        iconColor: 'rgb(var(--color-icon-green))', iconOpacity: '12%', group: 'management', roles: ADMIN_AND_ABOVE },
  // ── Personal (all roles) ──────────────────────────────────────────────────
  { label: 'My Teams',     path: '/my-teams',        piIcon: 'objects-column', iconColor: 'rgb(var(--color-icon-green))', iconOpacity: '12%', group: 'personal',   roles: ALL_ROLES },
  { label: 'My Keys',      path: '/my-keys',         piIcon: 'key',            iconColor: 'rgb(var(--color-icon-pink))', iconOpacity: '12%', group: 'personal',   roles: ALL_ROLES },
  { label: 'OpenCode',     path: '/open-code',       piIcon: 'code',           iconColor: 'rgb(var(--color-icon-yellow))', iconOpacity: '12%', group: 'personal',   roles: ALL_ROLES },
];

export const HOME_ROUTE: Record<UserRole, string> = {
  logos_admin:   '/dashboard',
  app_admin:     '/user-management',
  app_developer: '/my-teams',
};

export const NAV_GROUP_LABELS: Record<string, string> = {
  system:     'SYSTEM',
  management: 'MANAGEMENT',
  personal:   'PERSONAL',
};
