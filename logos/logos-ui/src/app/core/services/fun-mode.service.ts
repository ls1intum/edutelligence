import { Injectable, signal } from '@angular/core';

@Injectable({ providedIn: 'root' })
export class FunModeService {
  active = signal<boolean>(false);

  toggle(): void {
    this.active.update(v => !v);
  }
}
