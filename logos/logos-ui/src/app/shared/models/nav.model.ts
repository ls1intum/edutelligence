import { UserRole } from '../../core/auth/models/user.model';

export type NavGroup = 'system' | 'management' | 'personal';

export interface MenuItem {
  label: string;
  path: string;
  piIcon: string;
  iconColor: string;
  iconOpacity?: string;
  group: NavGroup;
  aliases?: string[];
  roles: UserRole[];
}
