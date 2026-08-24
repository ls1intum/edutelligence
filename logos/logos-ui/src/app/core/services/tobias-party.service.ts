import { Injectable, signal, effect, inject } from '@angular/core';
import { AuthService } from '../auth/services/auth.service';
import { FunModeService } from './fun-mode.service';

const CELEBRATION_DURATION_MS = 14000;
const TEQUILA_CUE_MS = 2500;
const CLIMAX_START_MS = 10000;
const GUEST_OF_HONOR = 'tobias wasner';

@Injectable({ providedIn: 'root' })
export class TobiasPartyService {
  private auth = inject(AuthService);
  private funMode = inject(FunModeService);

  active = signal(false);
  tequilaCue = signal(false);
  climax = signal(false);

  private wasGuestOfHonor = false;

  constructor() {
    effect(() => {
      const user = this.auth.currentUser();
      const isGuestOfHonor = !!user && `${user.prename} ${user.name}`.trim().toLowerCase() === GUEST_OF_HONOR;

      if (isGuestOfHonor && !this.wasGuestOfHonor) {
        this.celebrate();
      }
      this.wasGuestOfHonor = isGuestOfHonor;
    });
  }

  private celebrate(): void {
    this.active.set(true);
    this.tequilaCue.set(false);
    this.climax.set(false);
    this.funMode.active.set(true);

    setTimeout(() => this.tequilaCue.set(true), TEQUILA_CUE_MS);
    setTimeout(() => this.climax.set(true), CLIMAX_START_MS);
    setTimeout(() => {
      this.active.set(false);
      this.tequilaCue.set(false);
      this.climax.set(false);
    }, CELEBRATION_DURATION_MS);
  }
}
