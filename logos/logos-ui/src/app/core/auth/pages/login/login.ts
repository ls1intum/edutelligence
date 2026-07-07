import { Component, inject, signal, effect, ChangeDetectionStrategy, OnInit } from '@angular/core';
import { Router } from '@angular/router';
import { AuthService } from '../../services/auth.service';
import { keycloakIssuer, getPasskeyConfig } from '../../keycloak';
import { isPasskeySupported, loginWithPasskey, passkeyErrorMessage } from '../../passkey';
import { Logo } from '../../../../shared/components/logo/logo';
import { ThemeToggle } from '../../../../shared/components/theme-toggle/theme-toggle';
import { Orbs } from '../../../../shared/components/orbs/orbs';
import { ErrorMessageComponent } from '../../../../shared/components/error-message/error-message';

@Component({
  selector: 'app-login',
  standalone: true,
  imports: [Logo, ThemeToggle, Orbs, ErrorMessageComponent],
  templateUrl: './login.html',
  changeDetection: ChangeDetectionStrategy.Eager,
  styleUrl: './login.scss',
})
export class Login implements OnInit {
  private auth = inject(AuthService);
  private router = inject(Router);

  passkeyAvailable = signal(false);
  busy = signal(false);
  error = signal('');

  constructor() {
    // Route authenticated users onward — covers both the redirect-return from
    // Keycloak and an already-logged-in user hitting /login. The guards only
    // push unauthenticated users TO /login, never the reverse.
    effect(() => {
      if (this.auth.status() === 'authenticated') {
        const home = this.auth.role() === 'logos_admin' ? '/dashboard' : '/my-workspace';
        void this.router.navigateByUrl(home);
      }
    });
  }

  ngOnInit(): void {
    this.passkeyAvailable.set(isPasskeySupported());
  }

  signIn(): void {
    this.auth.login();
  }

  async signInWithPasskey(): Promise<void> {
    if (this.busy()) return;
    this.busy.set(true);
    this.error.set('');
    try {
      const kc = this.auth.keycloak;
      // #632: use the server-provided RP id (parent domain) when present; passing
      // undefined lets loginWithPasskey fall back to defaultRpId() (the hostname).
      const tokens = await loginWithPasskey(keycloakIssuer(kc), kc.clientId!, getPasskeyConfig().rpId);
      // Seamless, no redirect (exactly like the React app): hand the silently-
      // obtained tokens to keycloak-js; completeLogin → status 'authenticated'
      // → the routing effect navigates onward.
      await this.auth.completeLogin(tokens);
    } catch (e) {
      this.error.set(passkeyErrorMessage(e));
    } finally {
      this.busy.set(false);
    }
  }
}
