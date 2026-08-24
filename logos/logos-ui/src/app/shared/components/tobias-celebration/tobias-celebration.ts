import {
  Component,
  inject,
  ChangeDetectionStrategy,
  ElementRef,
  viewChild,
  effect,
} from '@angular/core';
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

interface FloatingLabel {
  x: number;
  y: number;
  vx: number;
  vy: number;
  phase: number;
  color: string;
}

const CONFETTI_COLORS = ['#ff5252', '#ffca28', '#66bb6a', '#42a5f5', '#ab47bc', '#ff7043', '#26c6da'];
const PARTICLES_PER_CORNER = 60;
const MAX_PARTICLES = 600;
const GRAVITY = 0.15;
const TEQUILA_SOUND_URL = 'duende-sounds.mp3';
const TEQUILA_SOUND_VOLUME = 0.6;
const FAESPENCER_TEQUILA_SOUND_URL = 'faespencer-tequila.mp3';
const FAESPENCER_TEQUILA_SOUND_VOLUME = 0.6;

const TEQUILA_LABEL_TEXT = '🥃 Tequila!';
const TEQUILA_LABEL_COUNT = 14;
const LABEL_EDGE_MARGIN = 60;
const CONFETTI_BURST_INTERVAL_MS = 1200;

@Component({
  selector: 'app-tobias-celebration',
  standalone: true,
  templateUrl: './tobias-celebration.html',
  changeDetection: ChangeDetectionStrategy.Eager,
  styleUrl: './tobias-celebration.scss',
})
export class TobiasCelebration {
  party = inject(TobiasPartyService);

  private canvasRef = viewChild<ElementRef<HTMLCanvasElement>>('confettiCanvas');

  private particles: ConfettiParticle[] = [];
  private floatingLabels: FloatingLabel[] = [];
  private animationFrameId: number | null = null;
  private confettiIntervalId: ReturnType<typeof setInterval> | null = null;

  private readonly onResize = (): void => {
    const canvas = this.canvasRef()?.nativeElement;
    if (canvas) {
      canvas.width = window.innerWidth;
      canvas.height = window.innerHeight;
    }
  };

  constructor() {
    effect(() => {
      if (this.party.active()) {
        this.start();
      } else {
        this.stop();
      }
    });

    effect(() => {
      if (this.party.tequilaCue()) {
        this.playFaespencerTequila();
      }
    });

    effect(() => {
      if (this.party.climax()) {
        this.enterClimax();
      }
    });
  }

  private start(): void {
    const canvas = this.canvasRef()?.nativeElement;
    if (!canvas) return;

    canvas.width = window.innerWidth;
    canvas.height = window.innerHeight;
    window.addEventListener('resize', this.onResize);

    document.body.classList.add('tobias-dance-mode');

    this.particles = [];
    this.floatingLabels = [];
    this.launchFromAllCorners(canvas.width, canvas.height);
    this.playTequila();

    this.confettiIntervalId = setInterval(() => {
      const c = this.canvasRef()?.nativeElement;
      if (c) this.launchFromAllCorners(c.width, c.height);
    }, CONFETTI_BURST_INTERVAL_MS);

    this.animate();
  }

  private stop(): void {
    window.removeEventListener('resize', this.onResize);
    document.body.classList.remove('tobias-dance-mode');

    if (this.animationFrameId !== null) {
      cancelAnimationFrame(this.animationFrameId);
      this.animationFrameId = null;
    }
    if (this.confettiIntervalId !== null) {
      clearInterval(this.confettiIntervalId);
      this.confettiIntervalId = null;
    }

    this.particles = [];
    this.floatingLabels = [];
    const canvas = this.canvasRef()?.nativeElement;
    canvas?.getContext('2d')?.clearRect(0, 0, canvas.width, canvas.height);
  }

  private enterClimax(): void {
    if (this.confettiIntervalId !== null) {
      clearInterval(this.confettiIntervalId);
      this.confettiIntervalId = null;
    }
    this.spawnFloatingLabels();
  }

  private spawnFloatingLabels(): void {
    const canvas = this.canvasRef()?.nativeElement;
    if (!canvas) return;

    for (let i = 0; i < TEQUILA_LABEL_COUNT; i++) {
      this.floatingLabels.push({
        x: Math.random() * canvas.width,
        y: Math.random() * canvas.height,
        vx: (Math.random() - 0.5) * 1.4,
        vy: (Math.random() - 0.5) * 1.4,
        phase: Math.random() * Math.PI * 2,
        color: CONFETTI_COLORS[Math.floor(Math.random() * CONFETTI_COLORS.length)],
      });
    }
  }

  private launchFromAllCorners(width: number, height: number): void {
    const quarterTurn = Math.PI / 2;
    this.spawnCornerBurst(0, 0, quarterTurn / 2);
    this.spawnCornerBurst(width, 0, Math.PI - quarterTurn / 2);
    this.spawnCornerBurst(0, height, -quarterTurn / 2);
    this.spawnCornerBurst(width, height, -Math.PI + quarterTurn / 2);
  }

  private spawnCornerBurst(x: number, y: number, baseAngle: number): void {
    for (let i = 0; i < PARTICLES_PER_CORNER; i++) {
      const angle = baseAngle + (Math.random() - 0.5) * (Math.PI / 3);
      const speed = 6 + Math.random() * 8;

      this.particles.push({
        x,
        y,
        vx: Math.cos(angle) * speed,
        vy: Math.sin(angle) * speed,
        size: 6 + Math.random() * 6,
        color: CONFETTI_COLORS[Math.floor(Math.random() * CONFETTI_COLORS.length)],
        rotation: Math.random() * Math.PI * 2,
        rotationSpeed: (Math.random() - 0.5) * 0.3,
      });
    }
  }

  private playTequila(): void {
    const audio = new Audio(TEQUILA_SOUND_URL);
    audio.volume = TEQUILA_SOUND_VOLUME;
    audio.play();
  }

  private playFaespencerTequila(): void {
    const audio = new Audio(FAESPENCER_TEQUILA_SOUND_URL);
    audio.volume = FAESPENCER_TEQUILA_SOUND_VOLUME;
    audio.play();
  }

  private animate(): void {
    if (!this.party.active()) return;

    const canvas = this.canvasRef()?.nativeElement;
    const ctx = canvas?.getContext('2d');
    if (!canvas || !ctx) return;

    ctx.clearRect(0, 0, canvas.width, canvas.height);

    for (const label of this.floatingLabels) {
      label.phase += 0.05;
      label.x += label.vx + Math.sin(label.phase) * 0.6;
      label.y += label.vy + Math.cos(label.phase) * 0.6;

      if (label.x < -LABEL_EDGE_MARGIN) label.x = canvas.width + LABEL_EDGE_MARGIN;
      if (label.x > canvas.width + LABEL_EDGE_MARGIN) label.x = -LABEL_EDGE_MARGIN;
      if (label.y < -LABEL_EDGE_MARGIN) label.y = canvas.height + LABEL_EDGE_MARGIN;
      if (label.y > canvas.height + LABEL_EDGE_MARGIN) label.y = -LABEL_EDGE_MARGIN;

      ctx.save();
      ctx.font = 'bold 20px sans-serif';
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';
      ctx.fillStyle = label.color;
      ctx.fillText(TEQUILA_LABEL_TEXT, label.x, label.y);
      ctx.restore();
    }

    this.particles = this.particles.filter(
      p => p.y < canvas.height + 30 && p.y > -30 && p.x > -30 && p.x < canvas.width + 30,
    );
    if (this.particles.length > MAX_PARTICLES) {
      this.particles.splice(0, this.particles.length - MAX_PARTICLES);
    }

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
