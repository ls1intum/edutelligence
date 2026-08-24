import { Injectable, inject, effect } from '@angular/core';
import { AuthService } from '../auth/services/auth.service';

const CHICKEN_SOUND_URL = 'chicken-sounds.mp3';
const CHICKEN_SOUND_VOLUME = 0.5;
const DETUNE_STEP_CENTS = 150;
const MAX_DETUNE_CENTS = 1800;

@Injectable({ providedIn: 'root' })
export class ChickenPitchService {
  private auth = inject(AuthService);

  private audioContext: AudioContext | null = null;
  private bufferPromise: Promise<AudioBuffer> | null = null;

  private pressCount = 0;
  private wasAuthenticated = false;

  constructor() {
    effect(() => {
      const authenticated = this.auth.status() === 'authenticated';
      if (authenticated && !this.wasAuthenticated) {
        this.pressCount = 0;
        this.play();
      }
      this.wasAuthenticated = authenticated;
    });
  }

  async play(): Promise<void> {
    const ctx = (this.audioContext ??= new AudioContext());
    if (ctx.state === 'suspended') {
      await ctx.resume();
    }

    const buffer = await this.loadBuffer(ctx);

    const source = ctx.createBufferSource();
    source.buffer = buffer;
    source.detune.value = Math.min(this.pressCount * DETUNE_STEP_CENTS, MAX_DETUNE_CENTS);
    this.pressCount += 1;

    const gain = ctx.createGain();
    gain.gain.value = CHICKEN_SOUND_VOLUME;

    source.connect(gain);
    gain.connect(ctx.destination);
    source.start();
  }

  private loadBuffer(ctx: AudioContext): Promise<AudioBuffer> {
    this.bufferPromise ??= fetch(CHICKEN_SOUND_URL)
      .then(response => response.arrayBuffer())
      .then(data => ctx.decodeAudioData(data));
    return this.bufferPromise;
  }
}
