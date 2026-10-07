import { ChangeDetectionStrategy, Component, Input, computed, signal } from '@angular/core';

/** Likert axes for the spider chart (extensible via inputs). */
export type ProfileAxis = { key: string; label: string };

const DEFAULT_AXES: ProfileAxis[] = [
  { key: 'latency', label: 'Latency' },
  { key: 'quality', label: 'Quality' },
  { key: 'price', label: 'Price' },
];

@Component({
  selector: 'app-model-profile-radar',
  standalone: true,
  templateUrl: './model-profile-radar.html',
  styleUrl: './model-profile-radar.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ModelProfileRadarComponent {
  /** Likert 1–5 ratings keyed by axis. Missing axes render as 0 (center). */
  @Input({ required: true }) set ratings(value: Record<string, number> | null | undefined) {
    this.ratingsSig.set(value ?? {});
  }
  @Input() set axes(value: ProfileAxis[] | null | undefined) {
    this.axesSig.set(value?.length ? value : DEFAULT_AXES);
  }
  @Input() size = 160;
  @Input() max = 5;

  private readonly ratingsSig = signal<Record<string, number>>({});
  private readonly axesSig = signal<ProfileAxis[]>(DEFAULT_AXES);

  readonly view = computed(() => {
    const axes = this.axesSig();
    const ratings = this.ratingsSig();
    const n = axes.length;
    const cx = this.size / 2;
    const cy = this.size / 2;
    const r = this.size * 0.36;
    const levels = Array.from({ length: this.max }, (_, i) => i + 1);

    const point = (index: number, value: number) => {
      const angle = -Math.PI / 2 + (index * 2 * Math.PI) / n;
      const t = Math.max(0, Math.min(this.max, value)) / this.max;
      return {
        x: cx + Math.cos(angle) * r * t,
        y: cy + Math.sin(angle) * r * t,
      };
    };

    const grid = levels.map((level) => {
      const pts = axes.map((_, i) => point(i, level));
      return pts.map((p) => `${p.x.toFixed(1)},${p.y.toFixed(1)}`).join(' ');
    });

    const spokes = axes.map((_, i) => {
      const tip = point(i, this.max);
      return { x1: cx, y1: cy, x2: tip.x, y2: tip.y };
    });

    // A label right of the centre starts at its spoke tip and one left of it ends
    // there, so it grows away from the chart instead of across it.
    const labels = axes.map((axis, i) => {
      const tip = point(i, this.max + 0.55);
      const dx = tip.x - cx;
      const anchor = dx > 4 ? 'start' : dx < -4 ? 'end' : 'middle';
      return {
        ...axis,
        x: tip.x + (anchor === 'start' ? 2 : anchor === 'end' ? -2 : 0),
        y: tip.y,
        anchor,
      };
    });

    const values = axes.map((axis, i) => {
      const raw = ratings[axis.key];
      const v = typeof raw === 'number' && raw >= 1 && raw <= this.max ? raw : 0;
      return point(i, v);
    });
    const polygon = values.map((p) => `${p.x.toFixed(1)},${p.y.toFixed(1)}`).join(' ');
    const hasAny = axes.some((a) => {
      const raw = ratings[a.key];
      return typeof raw === 'number' && raw >= 1 && raw <= this.max;
    });

    return { cx, cy, grid, spokes, labels, polygon, hasAny, size: this.size };
  });
}
