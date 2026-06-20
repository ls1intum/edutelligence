import { Component, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Router } from '@angular/router';
import { AuthService } from '../../services/auth.service';
import { Logo } from '../../../../shared/components/logo/logo';

@Component({
  selector: 'app-login',
  standalone: true,
  imports: [FormsModule, Logo],
  templateUrl: './login.html',
  styleUrl: './login.scss',
})
export class Login {
  private auth = inject(AuthService);
  private router = inject(Router);

  key = signal('');
  error = signal('');
  loading = signal(false);

  submit(): void {
    const k = this.key().trim();

    if (!k || this.loading()) return;

    this.loading.set(true);
    this.error.set('');

    this.auth.login(k).subscribe({
      next: ok => {
        this.loading.set(false);

        if (ok) {
          this.router.navigate(['/dashboard']);
        } else {
          this.error.set('Invalid or inactive API key.');
        }
      },
      error: () => {
        this.loading.set(false);
        this.error.set('Could not sign in. Please try again.');
      },
    });
  }
}
