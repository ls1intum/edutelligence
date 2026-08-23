import { UserRole } from '../../core/auth/models/user.model';

export type NavGroup = 'system' | 'management' | 'personal';

export interface MenuItem {
  label: string;
  path: string;
  piIcon: string;
  group: NavGroup;
  aliases?: string[];
  roles: UserRole[];
}
