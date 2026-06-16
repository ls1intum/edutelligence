import { Injectable, signal, computed } from '@angular/core';
import { User, UserRole } from '../models/user.model';

// Placeholder until Keycloak is integrated. Returns a hardcoded logos_admin so
// the shell and nav render correctly during development.
@Injectable({ providedIn: 'root' })
export class AuthService {
  currentUser = signal<User>({ username: 'dev', role: 'logos_admin' });
  role = computed<UserRole>(() => this.currentUser().role);
}
