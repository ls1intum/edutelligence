export type UserRole = 'logos_admin' | 'app_admin' | 'app_developer';

export interface User {
  username: string;
  role: UserRole;
  teamId?: string;
}
