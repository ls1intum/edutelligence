export type UserRole = 'logos_admin' | 'app_admin' | 'app_developer';

export interface Team {
  id: number;
  name: string;
}

export interface User {
  user_id: number;
  username: string;
  email: string;
  role: UserRole;
  teams: Team[];
}
