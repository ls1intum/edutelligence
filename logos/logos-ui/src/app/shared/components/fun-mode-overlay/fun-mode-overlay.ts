import {
  Component,
  inject,
  ChangeDetectionStrategy,
  ElementRef,
  viewChild,
  effect,
} from '@angular/core';
import { FunModeService } from '../../../core/services/fun-mode.service';
import { ChickenPitchService } from '../../../core/services/chicken-pitch.service';
import { TobiasPartyService } from '../../../core/services/tobias-party.service';

interface ConfettiParticle {
  x: number;
  y: number;
  vx: number;
  vy: number;
  size: number;
  color: string;
  rotation: number;
  rotationSpeed: number;
}

interface EggParticle {
  x: number;
  y: number;
  rotation: number;
  color: string;
  age: number;
  hatched: boolean;
}

const CONFETTI_COLORS = ['#ff5252', '#ffca28', '#66bb6a', '#42a5f5', '#ab47bc', '#ff7043', '#26c6da'];
const MAX_PARTICLES = 300;
const PARTICLES_PER_BURST = 45;
const LAUNCH_BURST_PARTICLES = 180;
const GRAVITY = 0.15;

const MAX_EGGS = 30;
const EGG_MIN_SPACING = 28;
const EGG_HATCH_AGE = 35;
const UNICORN_LIFE = 45;

const MOONWALK_MIN_DELAY_MS = 4000;
const MOONWALK_MAX_DELAY_MS = 9000;
const MOONWALK_DURATION_MS = 650;
const MOONWALK_NONSTOP_GAP_MS = MOONWALK_DURATION_MS + 150;
const MOONWALK_CLASS = 'fun-mode-overlay__hen-img--moonwalk';
const DRUNK_CLASS = 'fun-mode-overlay__hen-img--drunk';

@Component({
  selector: 'app-fun-mode-overlay',
  standalone: true,
  templateUrl: './fun-mode-overlay.html',
  changeDetection: ChangeDetectionStrategy.Eager,
  styleUrl: './fun-mode-overlay.scss',
})
export class FunModeOverlay {
  funMode = inject(FunModeService);
  private chickenPitch = inject(ChickenPitchService);
  private tobiasParty = inject(TobiasPartyService);

  private canvasRef = viewChild<ElementRef<HTMLCanvasElement>>('confettiCanvas');
  private henRef = viewChild<ElementRef<HTMLDivElement>>('hen');
  private henImgRef = viewChild<ElementRef<HTMLImageElement>>('henImg');

  private particles: ConfettiParticle[] = [];
  private eggs: EggParticle[] = [];
  private animationFrameId: number | null = null;
  private moonwalkTimeoutId: ReturnType<typeof setTimeout> | null = null;
  private moonwalkResetId: ReturnType<typeof setTimeout> | null = null;

  private lastEggX = 0;
  private lastEggY = 0;
  private hasLaidFirstEgg = false;

  private readonly onMouseMove = (event: MouseEvent): void => {
    this.moveHenTo(event.clientX, event.clientY);
  };

  private readonly onPointerDown = (event: PointerEvent): void => {
    this.spawnConfettiBurst(event.clientX, event.clientY, PARTICLES_PER_BURST);
    this.chickenPitch.play();
  };

  private readonly onResize = (): void => {
    const canvas = this.canvasRef()?.nativeElement;
    if (canvas) {
      canvas.width = window.innerWidth;
      canvas.height = window.innerHeight;
    }
  };

  constructor() {
    effect(() => {
      if (this.funMode.active()) {
        this.start();
      } else {
        this.stop();
      }
    });

    effect(() => {
      this.applyDrunkState(this.tobiasParty.climax());
    });
  }

  private applyDrunkState(drunk: boolean): void {
    const img = this.henImgRef()?.nativeElement;
    if (!img) return;

    if (drunk) {
      if (this.moonwalkTimeoutId !== null) {
        clearTimeout(this.moonwalkTimeoutId);
        this.moonwalkTimeoutId = null;
      }
      if (this.moonwalkResetId !== null) {
        clearTimeout(this.moonwalkResetId);
        this.moonwalkResetId = null;
      }
      img.classList.remove(MOONWALK_CLASS);
      img.classList.add(DRUNK_CLASS);
    } else {
      img.classList.remove(DRUNK_CLASS);
      if (this.funMode.active()) {
        this.scheduleMoonwalk();
      }
    }
  }

  private start(): void {
    const canvas = this.canvasRef()?.nativeElement;
    if (!canvas) return;

    canvas.width = window.innerWidth;
    canvas.height = window.innerHeight;

    window.addEventListener('mousemove', this.onMouseMove);
    window.addEventListener('pointerdown', this.onPointerDown);
    window.addEventListener('resize', this.onResize);
    document.body.classList.add('fun-mode-cursor-hidden');

    const centerX = window.innerWidth / 2;
    const centerY = window.innerHeight / 2;
    this.hasLaidFirstEgg = false;
    this.moveHenTo(centerX, centerY);

    this.particles = [];
    this.spawnConfettiBurst(centerX, centerY, LAUNCH_BURST_PARTICLES);
    this.scheduleMoonwalk();
    this.animate();
  }

  private stop(): void {
    window.removeEventListener('mousemove', this.onMouseMove);
    window.removeEventListener('pointerdown', this.onPointerDown);
    window.removeEventListener('resize', this.onResize);
    document.body.classList.remove('fun-mode-cursor-hidden');

    if (this.animationFrameId !== null) {
      cancelAnimationFrame(this.animationFrameId);
      this.animationFrameId = null;
    }
    if (this.moonwalkTimeoutId !== null) {
      clearTimeout(this.moonwalkTimeoutId);
      this.moonwalkTimeoutId = null;
    }
    if (this.moonwalkResetId !== null) {
      clearTimeout(this.moonwalkResetId);
      this.moonwalkResetId = null;
    }
    this.henImgRef()?.nativeElement.classList.remove(MOONWALK_CLASS, DRUNK_CLASS);

    this.particles = [];
    this.eggs = [];
    const canvas = this.canvasRef()?.nativeElement;
    canvas?.getContext('2d')?.clearRect(0, 0, canvas.width, canvas.height);
  }

  private scheduleMoonwalk(): void {
    const inTobiasOpening = this.tobiasParty.active() && !this.tobiasParty.climax();
    const delay = inTobiasOpening
      ? MOONWALK_NONSTOP_GAP_MS
      : MOONWALK_MIN_DELAY_MS + Math.random() * (MOONWALK_MAX_DELAY_MS - MOONWALK_MIN_DELAY_MS);

    this.moonwalkTimeoutId = setTimeout(() => {
      this.triggerMoonwalk();
      this.scheduleMoonwalk();
    }, delay);
  }

  private triggerMoonwalk(): void {
    const img = this.henImgRef()?.nativeElement;
    if (!img) return;

    if (this.moonwalkResetId !== null) {
      clearTimeout(this.moonwalkResetId);
    }

    img.classList.remove(MOONWALK_CLASS);
    void img.offsetWidth;
    img.classList.add(MOONWALK_CLASS);

    this.moonwalkResetId = setTimeout(() => img.classList.remove(MOONWALK_CLASS), MOONWALK_DURATION_MS);
  }

  private moveHenTo(x: number, y: number): void {
    const hen = this.henRef()?.nativeElement;
    if (!hen) return;

    if (!this.hasLaidFirstEgg) {
      this.lastEggX = x;
      this.lastEggY = y;
      this.hasLaidFirstEgg = true;
    } else if (Math.hypot(x - this.lastEggX, y - this.lastEggY) >= EGG_MIN_SPACING) {
      this.eggs.push({
        x: this.lastEggX,
        y: this.lastEggY,
        rotation: Math.random() * Math.PI * 2,
        color: CONFETTI_COLORS[Math.floor(Math.random() * CONFETTI_COLORS.length)],
        age: 0,
        hatched: false,
      });
      if (this.eggs.length > MAX_EGGS) {
        this.eggs.shift();
      }
      this.lastEggX = x;
      this.lastEggY = y;
    }

    hen.style.transform = `translate(${x}px, ${y}px) translate(-50%, -50%)`;
  }

  private spawnConfettiBurst(x: number, y: number, count: number): void {
    for (let i = 0; i < count; i++) {
      const angle = Math.random() * Math.PI * 2;
      const speed = 2 + Math.random() * 7;

      this.particles.push({
        x,
        y,
        vx: Math.cos(angle) * speed,
        vy: Math.sin(angle) * speed - 4,
        size: 6 + Math.random() * 6,
        color: CONFETTI_COLORS[Math.floor(Math.random() * CONFETTI_COLORS.length)],
        rotation: Math.random() * Math.PI * 2,
        rotationSpeed: (Math.random() - 0.5) * 0.3,
      });
    }

    if (this.particles.length > MAX_PARTICLES) {
      this.particles.splice(0, this.particles.length - MAX_PARTICLES);
    }
  }

  private animate(): void {
    if (!this.funMode.active()) return;

    const canvas = this.canvasRef()?.nativeElement;
    const ctx = canvas?.getContext('2d');
    if (!canvas || !ctx) return;

    ctx.clearRect(0, 0, canvas.width, canvas.height);

    this.eggs = this.eggs.filter(egg => !(egg.hatched && egg.age > UNICORN_LIFE));
    for (const egg of this.eggs) {
      egg.age += 1;

      if (!egg.hatched && egg.age > EGG_HATCH_AGE) {
        egg.hatched = true;
        egg.age = 0;
      }

      if (!egg.hatched) {
        ctx.save();
        ctx.translate(egg.x, egg.y);
        ctx.rotate(egg.rotation);
        ctx.fillStyle = egg.color;
        ctx.strokeStyle = 'rgb(255 255 255 / 0.6)';
        ctx.lineWidth = 1.5;
        ctx.beginPath();
        ctx.ellipse(0, 0, 7, 9, 0, 0, Math.PI * 2);
        ctx.fill();
        ctx.stroke();
        ctx.restore();
      } else {
        const t = egg.age / UNICORN_LIFE;
        const opacity = Math.max(1 - t, 0);
        const scale = Math.min(t * 4, 1);

        ctx.save();
        ctx.globalAlpha = opacity;
        ctx.translate(egg.x, egg.y - t * 30);
        ctx.scale(scale, scale);
        ctx.font = '22px serif';
        ctx.textAlign = 'center';
        ctx.textBaseline = 'middle';
        ctx.fillText('🦄', 0, 0);
        ctx.restore();
      }
    }

    this.particles = this.particles.filter(p => p.y < canvas.height + 30);
    for (const particle of this.particles) {
      particle.vy += GRAVITY;
      particle.x += particle.vx;
      particle.y += particle.vy;
      particle.rotation += particle.rotationSpeed;

      ctx.save();
      ctx.translate(particle.x, particle.y);
      ctx.rotate(particle.rotation);
      ctx.fillStyle = particle.color;
      ctx.fillRect(-particle.size / 2, -particle.size / 2, particle.size, particle.size * 0.6);
      ctx.restore();
    }

    this.animationFrameId = requestAnimationFrame(() => this.animate());
  }
}
