import { Component, inject, signal, ChangeDetectionStrategy } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Router } from '@angular/router';
import { AuthService } from '../../services/auth.service';
import { Logo } from '../../../../shared/components/logo/logo';
import { ThemeToggle } from '../../../../shared/components/theme-toggle/theme-toggle';
import { Orbs } from '../../../../shared/components/orbs/orbs';
import { ErrorMessageComponent } from '../../../../shared/components/error-message/error-message';

@Component({
  selector: 'app-login',
  standalone: true,
  imports: [FormsModule, Logo, ThemeToggle, Orbs, ErrorMessageComponent],
  templateUrl: './login.html',
  changeDetection: ChangeDetectionStrategy.Eager,
  styleUrl: './login.scss',
})
export class Login {
  private auth = inject(AuthService);
  private router = inject(Router);

  key = signal('');
  error = signal('');
  loading = signal(false);

  async submit(): Promise<void> {
    const k = this.key().trim();

    if (!k || this.loading()) return;

    this.loading.set(true);
    this.error.set('');

    try {
      const ok = await this.auth.login(k);
      this.loading.set(false);
      if (ok) {
        this.router.navigate(['/dashboard']);
      } else {
        this.error.set('Invalid or inactive API key.');
      }
    } catch {
      this.loading.set(false);
      this.error.set('Could not sign in. Please try again.');
    }
  }
}
