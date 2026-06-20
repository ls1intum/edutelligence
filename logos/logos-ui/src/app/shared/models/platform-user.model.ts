import { UserRole } from '../../core/auth/models/user.model';

export interface PlatformUser {
  id: number;
  username: string;
  prename: string;
  name: string;
  email: string;
  role: UserRole;
  teams: { id: number; name: string }[];
}
