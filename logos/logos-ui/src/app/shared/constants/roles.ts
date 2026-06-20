import { UserRole } from '../../core/auth/models/user.model';

export const ROLE_LABELS: Record<UserRole, string> = {
  logos_admin:   'Logos Admin',
  app_admin:     'App Admin',
  app_developer: 'App Developer',
};

export const ALL_ROLES: UserRole[] = ['logos_admin', 'app_admin', 'app_developer'];

export const ROLE_COLORS: Record<UserRole, string> = {
  logos_admin:   'var(--color-icon-pink)',
  app_admin:     'var(--color-icon-orange)',
  app_developer: 'var(--color-icon-purple)',
};

export const ROLE_DESCRIPTIONS: Record<UserRole, string> = {
  logos_admin:   'Full platform access and user administration',
  app_admin:     'Manage application settings and users',
  app_developer: 'Access developer tools and application features',
};
