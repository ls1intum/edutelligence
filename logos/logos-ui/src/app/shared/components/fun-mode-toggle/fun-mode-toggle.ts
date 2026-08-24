import { Component, inject, ChangeDetectionStrategy } from '@angular/core';
import { FunModeService } from '../../../core/services/fun-mode.service';

@Component({
  selector: 'app-fun-mode-toggle',
  standalone: true,
  templateUrl: './fun-mode-toggle.html',
  changeDetection: ChangeDetectionStrategy.Eager,
  styleUrl: './fun-mode-toggle.scss',
})
export class FunModeToggle {
  funMode = inject(FunModeService);
}
