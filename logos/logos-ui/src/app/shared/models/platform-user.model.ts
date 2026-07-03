import { UserRole } from '../../core/auth/models/user.model';

export interface PlatformUser {
  id: number;
  username: string;
  prename: string;
  name: string;
  email: string;
  role: UserRole;
  teams: { id: number; name: string }[];
  /** True when provisioned from Keycloak; identity, role and existence are Keycloak-owned and cannot be edited here. */
  managed: boolean;
}
