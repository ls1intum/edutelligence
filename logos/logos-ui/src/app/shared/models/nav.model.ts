import { UserRole } from '../../core/auth/models/user.model';

export interface MenuItem {
  label: string;
  path: string;
  piIcon: string;
  aliases?: string[];
  roles: UserRole[];
}
