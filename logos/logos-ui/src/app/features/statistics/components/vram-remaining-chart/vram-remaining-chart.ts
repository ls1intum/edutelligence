import {
  Component,
  computed,
  EventEmitter,
  Input,
  OnChanges,
  Output,
  signal,
  SimpleChanges,
  ChangeDetectionStrategy,
} from '@angular/core';
import { StatsSkeletonComponent } from '../skeletons/skeletons';
import { VramRangeSliderComponent } from '../vram-range-slider/vram-range-slider';
import { seriesColor } from '../../statistics.constants';
import { parseVramSnapshot, timeAxisLabels } from '../../statistics.utils';
import type { VramV2Sample, VramProviderMeta, LaneSignalData } from '../../statistics.models';
import { pointerPlotFrac, nearestIndex } from '../chart-interaction.util';

// ── SVG geometry ─────────────────────────────────────────────────────────────
const CHART_W = 1000;
const CHART_H = 200;
const CHART_PAD_LEFT = 44;
const CHART_PAD_BOTTOM = 24;
const CHART_PAD_TOP = 8;
const CHART_PAD_RIGHT = 8;

/** If the newest sample is older than this, flag it as stale in the badge. */
const STALENESS_LIMIT_MS = 5 * 60_000;

// ── Types ─────────────────────────────────────────────────────────────────────

interface PlotPoint {
  x: number;
  y: number;
}

interface ProviderSeries {
  name: string;
  color: string;
  /** Raw {x,y} before clamping to visible window */
  points: PlotPoint[];
  /** SVG area path (M…L…Z closing to baseline) */
  areaPath: string;
  /** SVG polyline points string for the top line */
  linePoints: string;
}

interface GridLine {
  y: number;
  label: string;
}
interface XLabel {
  x: number;
  label: string;
}

interface ChartOutput {
  series: ProviderSeries[];
  gridLines: GridLine[];
  xLabels: XLabel[];
  plotLeft: number;
  plotRight: number;
  plotTop: number;
  plotBottom: number;
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function niceMax(raw: number): number {
  if (raw <= 0) return 1;
  const mag = Math.pow(10, Math.floor(Math.log10(raw)));
  const n = raw / mag;
  const nice = n <= 1.5 ? 1.5 : n <= 3 ? 3 : n <= 7 ? 7 : 10;
  return nice * mag;
}

function formatGb(v: number): string {
  if (v >= 1000) return `${(v / 1000).toFixed(1)}k GB`;
  return `${v.toFixed(0)} GB`;
}

// ── Component ─────────────────────────────────────────────────────────────────

@Component({
  selector: 'app-stats-vram-remaining-chart',
  standalone: true,
  imports: [StatsSkeletonComponent, VramRangeSliderComponent],
  templateUrl: './vram-remaining-chart.html',
  changeDetection: ChangeDetectionStrategy.Eager,
  styleUrl: './vram-remaining-chart.scss',
})
export class VramRemainingChartComponent implements OnChanges {
  // ── Inputs ──────────────────────────────────────────────────────────────────
  @Input() vramDataByProvider: Record<string, VramV2Sample[]> = {};
  @Input() providerMetaByName: Record<string, VramProviderMeta> = {};
  /**
   * The global (user-selected) time range. The always-live 'all' VRAM dataset
   * is windowed over this range; the range slider only zooms inside it.
   */
  @Input() timeRange: { startMs: number; endMs: number } = { startMs: 0, endMs: 0 };
  @Input() isVramLoading = false;
  @Input() vramError: string | null = null;
  @Input() nowMs = Date.now();
  @Input() laneStateByProvider: Record<string, Record<string, LaneSignalData>> = {};

  // ── Outputs ─────────────────────────────────────────────────────────────────
  @Output() refresh = new EventEmitter<void>();

  // ── Internal state ───────────────────────────────────────────────────────────
  // Input mirror signals so computed() reacts on ngOnChanges
  private readonly _data = signal<Record<string, VramV2Sample[]>>({});
  private readonly _range = signal<{ startMs: number; endMs: number }>({ startMs: 0, endMs: 0 });
  private readonly _nowMs = signal(Date.now());

  /** Hover fraction (0..1 across the plot area). null = no hover. */
  readonly hoverIndex = signal<number | null>(null);

  /** Slider-controlled zoom window (ms) inside the global range. 0 = no zoom. */
  readonly visibleStart = signal<number>(0);
  readonly visibleEnd = signal<number>(0);

  // ── Public chart constants (exposed to template) ─────────────────────────────
  readonly CHART_W = CHART_W;
  readonly CHART_H = CHART_H;
  readonly CHART_PAD_LEFT = CHART_PAD_LEFT;
  readonly CHART_PAD_BOTTOM = CHART_PAD_BOTTOM;
  readonly CHART_PAD_TOP = CHART_PAD_TOP;
  readonly CHART_PAD_RIGHT = CHART_PAD_RIGHT;

  // ── Latest sample timestamp across all providers ─────────────────────────────
  readonly latestSampleMs = computed((): number | null => {
    const data = this._data();
    let best: number | null = null;
    for (const samples of Object.values(data)) {
      for (const s of samples) {
        const t = new Date(s.timestamp).getTime();
        if (Number.isFinite(t) && (best === null || t > best)) best = t;
      }
    }
    return best;
  });

  /** Formatted last-sample time for the badge */
  readonly lastSampleLabel = computed((): string | null => {
    const ts = this.latestSampleMs();
    if (ts === null) return null;
    const d = new Date(ts);
    const now = this._nowMs();
    const ageMs = Math.max(0, now - ts);
    const isStale = ageMs > STALENESS_LIMIT_MS;
    const time = d.toLocaleTimeString('en-GB', {
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
      timeZone: 'UTC',
    });
    if (isStale) {
      const s = Math.round(ageMs / 1000);
      const m = Math.round(s / 60);
      const h = Math.round(m / 60);
      const age =
        s < 60
          ? `${s}s ago`
          : m < 60
            ? `${m}m ago`
            : h < 48
              ? `${h}h ago`
              : `${Math.round(h / 24)}d ago`;
      return `${time} UTC · stale (${age})`;
    }
    return `${time} UTC`;
  });

  /** True if the last sample is older than STALENESS_LIMIT_MS */
  readonly isStale = computed(() => {
    const ts = this.latestSampleMs();
    if (ts === null) return false;
    return this._nowMs() - ts > STALENESS_LIMIT_MS;
  });

  // ── Visible window (global range, optionally zoomed by the slider) ──────────
  private readonly _visibleWindow = computed((): { winStartMs: number; winEndMs: number } => {
    const range = this._range();
    const sliderStart = this.visibleStart();
    const sliderEnd = this.visibleEnd();
    if (sliderStart !== 0 && sliderEnd !== 0 && sliderEnd > sliderStart) {
      return { winStartMs: sliderStart, winEndMs: sliderEnd };
    }
    return { winStartMs: range.startMs, winEndMs: range.endMs };
  });

  // ── Chart computation ────────────────────────────────────────────────────────
  readonly chartData = computed((): ChartOutput => {
    const data = this._data();
    const { winStartMs, winEndMs } = this._visibleWindow();

    const empty: ChartOutput = {
      series: [],
      gridLines: [],
      xLabels: [],
      plotLeft: CHART_PAD_LEFT,
      plotRight: CHART_W - CHART_PAD_RIGHT,
      plotTop: CHART_PAD_TOP,
      plotBottom: CHART_H - CHART_PAD_BOTTOM,
    };

    const providers = Object.keys(data);
    if (providers.length === 0) return empty;

    if (!Number.isFinite(winStartMs) || !Number.isFinite(winEndMs) || winEndMs <= winStartMs) {
      return empty;
    }

    const winDurMs = Math.max(winEndMs - winStartMs, 1);

    const plotW = CHART_W - CHART_PAD_LEFT - CHART_PAD_RIGHT;
    const plotH = CHART_H - CHART_PAD_TOP - CHART_PAD_BOTTOM;
    const base = CHART_PAD_TOP + plotH; // y-coordinate of baseline

    // ── Build raw points per provider ────────────────────────────────────────
    type RawPt = { tsMs: number; gb: number };
    const rawBySeries: { name: string; pts: RawPt[] }[] = providers
      .map((name) => {
        const samples = data[name] ?? [];
        const pts: RawPt[] = [];
        for (const s of samples) {
          const tsMs = new Date(s.timestamp).getTime();
          if (!Number.isFinite(tsMs)) continue;
          const gb = parseVramSnapshot(s).remainingGb;
          pts.push({ tsMs, gb });
        }
        pts.sort((a, b) => a.tsMs - b.tsMs);
        return { name, pts };
      })
      .filter((s) => s.pts.length > 0);

    if (rawBySeries.length === 0) return empty;

    // ── Compute y-scale across all points in visible window ─────────────────
    let maxGb = 0;
    for (const { pts } of rawBySeries) {
      for (const p of pts) {
        if (p.tsMs >= winStartMs && p.tsMs <= winEndMs && p.gb > maxGb) {
          maxGb = p.gb;
        }
      }
    }
    // Fallback: use all data if nothing in window
    if (maxGb === 0) {
      for (const { pts } of rawBySeries) {
        for (const p of pts) {
          if (p.gb > maxGb) maxGb = p.gb;
        }
      }
    }
    const yMax = niceMax(maxGb);

    // ── Helper: ts → svg-x ───────────────────────────────────────────────────
    const tsToX = (tsMs: number): number =>
      CHART_PAD_LEFT + ((tsMs - winStartMs) / winDurMs) * plotW;

    const gbToY = (gb: number): number => CHART_PAD_TOP + plotH * (1 - Math.min(gb / yMax, 1));

    // ── Build per-provider SVG paths ─────────────────────────────────────────
    const series: ProviderSeries[] = rawBySeries.map(({ name, pts }, idx) => {
      const color = seriesColor(idx);

      // Build {x,y} points
      const plotPts: PlotPoint[] = pts.map((p) => ({
        x: tsToX(p.tsMs),
        y: gbToY(p.gb),
      }));

      // Area path: move to first point, line across all, close to baseline
      let areaPath = '';
      if (plotPts.length > 0) {
        const first = plotPts[0];
        const last = plotPts[plotPts.length - 1];
        areaPath = `M${first.x},${base} L${first.x},${first.y}`;
        for (let i = 1; i < plotPts.length; i++) {
          areaPath += ` L${plotPts[i].x},${plotPts[i].y}`;
        }
        areaPath += ` L${last.x},${base} Z`;
      }

      // Polyline points string for the top line
      const linePoints = plotPts.map((p) => `${p.x},${p.y}`).join(' ');

      return { name, color, points: plotPts, areaPath, linePoints };
    });

    // ── Grid lines ───────────────────────────────────────────────────────────
    const gridLines: GridLine[] = [0.25, 0.5, 0.75, 1.0].map((f) => ({
      y: CHART_PAD_TOP + plotH * (1 - f),
      label: formatGb(f * yMax),
    }));

    // ── X-axis labels (adaptive to the window span, always unambiguous) ──────
    const xLabels = timeAxisLabels(winStartMs, winEndMs, 8).map((l) => {
      const x = tsToX(l.tsMs);
      if (x < CHART_PAD_LEFT || x > CHART_W - CHART_PAD_RIGHT) return null;
      return { x, label: l.label };
    }).filter((l): l is XLabel => l !== null);

    return {
      series,
      gridLines,
      xLabels,
      plotLeft: CHART_PAD_LEFT,
      plotRight: CHART_W - CHART_PAD_RIGHT,
      plotTop: CHART_PAD_TOP,
      plotBottom: CHART_H - CHART_PAD_BOTTOM,
    };
  });

  // ── Derived: has any data ────────────────────────────────────────────────────
  readonly hasData = computed(() => {
    const data = this._data();
    return Object.values(data).some((arr) => arr.length > 0);
  });

  /** True when the visible (zoomed) window differs from the full range. */
  readonly isZoomed = computed(
    () =>
      this.visibleStart() !== 0 &&
      this.visibleEnd() !== 0 &&
      (this.visibleStart() !== this._range().startMs || this.visibleEnd() !== this._range().endMs),
  );

  // ── Crosshair computed ───────────────────────────────────────────────────────
  readonly crosshair = computed((): {
    x: number;
    rows: { label: string; usedGb: number; remainingGb: number; totalGb: number; color: string }[];
    timeLabel: string;
  } | null => {
    const frac = this.hoverIndex();
    if (frac === null) return null;

    const data = this._data();
    const providers = Object.keys(data);
    if (providers.length === 0) return null;

    const { winStartMs, winEndMs } = this._visibleWindow();
    const winDurMs = Math.max(winEndMs - winStartMs, 1);

    // Convert fraction to a timestamp within the visible window
    const hoveredMs = winStartMs + frac * winDurMs;

    // SVG x position (viewBox units)
    const plotW = CHART_W - CHART_PAD_LEFT - CHART_PAD_RIGHT;
    const x = CHART_PAD_LEFT + frac * plotW;

    // For each provider, find the nearest sample by time
    const rows: { label: string; usedGb: number; remainingGb: number; totalGb: number; color: string }[] = [];
    let bestTs: number | null = null;

    providers.forEach((name, idx) => {
      const samples = data[name] ?? [];
      if (samples.length === 0) return;

      // Sort and find nearest by time
      const sorted = [...samples]
        .map((s) => ({ s, tsMs: new Date(s.timestamp).getTime() }))
        .filter((p) => Number.isFinite(p.tsMs))
        .sort((a, b) => a.tsMs - b.tsMs);

      if (sorted.length === 0) return;

      const nearestIdx = nearestIndex(frac, sorted.length);
      const { s, tsMs } = sorted[nearestIdx];

      if (bestTs === null || Math.abs(tsMs - hoveredMs) < Math.abs(bestTs - hoveredMs)) {
        bestTs = tsMs;
      }

      const parsed = parseVramSnapshot(s);
      rows.push({
        label: name,
        usedGb: parsed.usedGb,
        remainingGb: parsed.remainingGb,
        totalGb: parsed.totalGb,
        color: seriesColor(idx),
      });
    });

    if (rows.length === 0) return null;

    const ts = bestTs ?? hoveredMs;
    const d = new Date(ts);
    const timeLabel = d.toLocaleTimeString('en-GB', {
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
      timeZone: 'UTC',
    }) + ' UTC';

    return { x, rows, timeLabel };
  });

  // ── Crosshair / hover handlers ───────────────────────────────────────────────
  onPlotMove(event: MouseEvent): void {
    const svgEl = event.currentTarget as Element;
    const svg = (svgEl.tagName === 'svg' ? svgEl : svgEl.closest('svg')) as SVGSVGElement | null;
    const frac = pointerPlotFrac(event, svg, CHART_W, CHART_PAD_LEFT, CHART_PAD_RIGHT);
    if (frac === null) {
      this.hoverIndex.set(null);
      return;
    }
    const data = this._data();
    const providers = Object.keys(data);
    // Use the length of the densest provider to snap to a meaningful sample
    const maxN = providers.reduce((m, k) => Math.max(m, (data[k] ?? []).length), 0);
    if (maxN > 0) {
      // Store nearest-index fraction as a pure fraction (not a bucket index)
      // We keep it as-is since crosshair uses it to reconstruct the timestamp
      this.hoverIndex.set(frac);
    } else {
      this.hoverIndex.set(null);
    }
  }

  onPlotLeave(): void {
    this.hoverIndex.set(null);
  }

  /** Restore the full (unzoomed) range view. */
  resetView(): void {
    this.visibleStart.set(0);
    this.visibleEnd.set(0);
  }

  /** Handle slider window-change event. */
  setVisibleWindow(w: { start: number; end: number }): void {
    this.visibleStart.set(w.start);
    this.visibleEnd.set(w.end);
  }

  // ── ngOnChanges bridge ──────────────────────────────────────────────────────
  ngOnChanges(changes: SimpleChanges): void {
    if (changes['vramDataByProvider']) this._data.set(this.vramDataByProvider);
    if (changes['timeRange']) {
      this._range.set(this.timeRange);
      // Reset the zoom window when the global range changes
      this.visibleStart.set(0);
      this.visibleEnd.set(0);
    }
    if (changes['nowMs']) this._nowMs.set(this.nowMs);
  }

  // ── Formatters ───────────────────────────────────────────────────────────────
  formatGb(v: number): string {
    return formatGb(v);
  }
}
