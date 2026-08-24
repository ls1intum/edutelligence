import { Component, inject, OnInit, ChangeDetectionStrategy, signal, effect } from '@angular/core';
import { RouterOutlet } from '@angular/router';
import { ThemeService } from './core/services/theme.service';
import { FunModeService } from './core/services/fun-mode.service';
import { TobiasPartyService } from './core/services/tobias-party.service';
import { FunModeToggle } from './shared/components/fun-mode-toggle/fun-mode-toggle';
import { FunModeOverlay } from './shared/components/fun-mode-overlay/fun-mode-overlay';
import { TobiasCelebration } from './shared/components/tobias-celebration/tobias-celebration';

const SHAKE_DURATION_MS = 400;

@Component({
  selector: 'app-root',
  imports: [RouterOutlet, FunModeToggle, FunModeOverlay, TobiasCelebration],
  templateUrl: './app.html',
  changeDetection: ChangeDetectionStrategy.Eager,
  styleUrl: './app.scss',
})
export class App implements OnInit {
  private theme = inject(ThemeService);
  funMode = inject(FunModeService);
  tobiasParty = inject(TobiasPartyService);
  shaking = signal(false);

  private wasFunModeActive = false;

  constructor() {
    effect(() => {
      const active = this.funMode.active();
      if (active && !this.wasFunModeActive) {
        this.shaking.set(true);
        setTimeout(() => this.shaking.set(false), SHAKE_DURATION_MS);
      }
      this.wasFunModeActive = active;
    });
  }

  ngOnInit(): void {
    this.theme.isDark();
  }
}
