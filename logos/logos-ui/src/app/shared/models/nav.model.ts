import { UserRole } from '../../core/auth/models/user.model';
import { AccentColor } from '../utils/avatar';

export type NavGroup = 'system' | 'management' | 'personal';

export interface MenuItem {
  label: string;
  path: string;
  piIcon: string;
  accentColor: AccentColor;
  group: NavGroup;
  aliases?: string[];
  roles: UserRole[];
}
