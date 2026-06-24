import { Component, inject, ChangeDetectionStrategy } from '@angular/core';
import { ThemeService } from '../../../core/services/theme.service';

@Component({
  selector: 'app-theme-toggle',
  standalone: true,
  templateUrl: './theme-toggle.html',
  changeDetection: ChangeDetectionStrategy.Eager,
  styleUrl: './theme-toggle.scss',
})
export class ThemeToggle {
  theme = inject(ThemeService);
}
