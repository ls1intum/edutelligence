import { Injectable, signal, effect, inject } from '@angular/core';
import { PrimeNG } from 'primeng/config';

@Injectable({ providedIn: 'root' })
export class ThemeService {
  private readonly STORAGE_KEY = 'logos-theme';
  private primeNG = inject(PrimeNG);

  isDark = signal<boolean>(this.loadPreference());

  constructor() {
    effect(() => {
      const dark = this.isDark();
      document.documentElement.setAttribute('data-theme', dark ? 'dark' : 'light');
      this.primeNG.theme.update(t => ({
        ...t,
        options: { ...t.options, darkModeSelector: '[data-theme="dark"]' },
      }));
      localStorage.setItem(this.STORAGE_KEY, dark ? 'dark' : 'light');
    });
  }

  toggle(): void {
    this.isDark.update(v => !v);
  }

  private loadPreference(): boolean {
    const stored = localStorage.getItem(this.STORAGE_KEY);
    if (stored) return stored === 'dark';
    return window.matchMedia('(prefers-color-scheme: dark)').matches;
  }
}
