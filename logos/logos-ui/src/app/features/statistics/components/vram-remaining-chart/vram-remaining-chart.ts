import {
  Component,
  computed,
  EventEmitter,
  Input,
  OnChanges,
  Output,
  signal,
  SimpleChanges,
} from '@angular/core';
import { SegmentedSwitchComponent } from '../segmented-switch/segmented-switch';
import { StatsSkeletonComponent } from '../skeletons/skeletons';
import { seriesColor } from '../../statistics.constants';
import { parseVramSnapshot } from '../../statistics.utils';
import type { VramV2Sample, VramProviderMeta, LaneSignalData } from '../../statistics.models';

// ── Live-window constants ─────────────────────────────────────────────────────
const LIVE_WINDOW_MINUTES = 30;
const LIVE_WINDOW_MS      = LIVE_WINDOW_MINUTES * 60_000;
const LIVE_RIGHT_PAD_MS   = 60_000;
/** If the newest sample is older than this, anchor the live window to the
 *  data rather than wall-clock so the chart doesn't look empty. */
const LIVE_STALENESS_LIMIT_MS = 5 * 60_000;

// ── SVG geometry ─────────────────────────────────────────────────────────────
const CHART_W          = 1000;
const CHART_H          = 200;
const CHART_PAD_LEFT   = 44;
const CHART_PAD_BOTTOM = 24;
const CHART_PAD_TOP    = 8;
const CHART_PAD_RIGHT  = 8;

// ── Types ─────────────────────────────────────────────────────────────────────

type ViewMode = 'live' | 'full';

interface PlotPoint { x: number; y: number; }

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

interface GridLine { y: number; label: string; }
interface XLabel   { x: number; label: string; }

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
  const mag  = Math.pow(10, Math.floor(Math.log10(raw)));
  const n    = raw / mag;
  const nice = n <= 1.5 ? 1.5 : n <= 3 ? 3 : n <= 7 ? 7 : 10;
  return nice * mag;
}

function formatGb(v: number): string {
  if (v >= 1000) return `${(v / 1000).toFixed(1)}k GB`;
  return `${v.toFixed(0)} GB`;
}

/** UTC day start (ms) for `nowMs - offsetDays * DAY_MS`. */
function utcDayStart(nowMs: number, offsetDays: number): number {
  const d = new Date(nowMs - offsetDays * 86_400_000);
  return Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), d.getUTCDate());
}

function periodLabel(offset: number, nowMs: number): string {
  if (offset === 0) return 'Today';
  if (offset === 1) return 'Yesterday';
  const d = new Date(utcDayStart(nowMs, offset));
  return d.toLocaleDateString('en-US', {
    month: 'short', day: 'numeric', year: 'numeric', timeZone: 'UTC',
  });
}

// ── Component ─────────────────────────────────────────────────────────────────

@Component({
  selector: 'app-stats-vram-remaining-chart',
  standalone: true,
  imports: [SegmentedSwitchComponent, StatsSkeletonComponent],
  templateUrl: './vram-remaining-chart.html',
  styleUrl: './vram-remaining-chart.scss',
})
export class VramRemainingChartComponent implements OnChanges {
  // ── Inputs ──────────────────────────────────────────────────────────────────
  @Input() vramDataByProvider: Record<string, VramV2Sample[]>              = {};
  @Input() providerMetaByName: Record<string, VramProviderMeta>            = {};
  @Input() vramDayOffset                                                    = 0;
  @Input() isVramLoading                                                    = false;
  @Input() vramError: string | null                                         = null;
  @Input() nowMs                                                            = Date.now();
  @Input() laneStateByProvider: Record<string, Record<string, LaneSignalData>> = {};

  // ── Outputs ─────────────────────────────────────────────────────────────────
  @Output() vramDayOffsetChange = new EventEmitter<number>();
  @Output() refresh             = new EventEmitter<void>();

  // ── Internal state ───────────────────────────────────────────────────────────
  /** Live / Full History toggle */
  readonly view = signal<ViewMode>('live');

  // Input mirror signals so computed() reacts on ngOnChanges
  private readonly _data    = signal<Record<string, VramV2Sample[]>>({});
  private readonly _offset  = signal(0);
  private readonly _nowMs   = signal(Date.now());

  // ── Public chart constants (exposed to template) ─────────────────────────────
  readonly CHART_W          = CHART_W;
  readonly CHART_H          = CHART_H;
  readonly CHART_PAD_LEFT   = CHART_PAD_LEFT;
  readonly CHART_PAD_BOTTOM = CHART_PAD_BOTTOM;
  readonly CHART_PAD_TOP    = CHART_PAD_TOP;
  readonly CHART_PAD_RIGHT  = CHART_PAD_RIGHT;

  // ── Segmented-switch options ─────────────────────────────────────────────────
  readonly viewOptions = [
    { value: 'live', label: `Live (${LIVE_WINDOW_MINUTES}m)` },
    { value: 'full', label: 'Full History' },
  ];

  // ── Period label (day-nav) ───────────────────────────────────────────────────
  readonly periodLabel = computed(() =>
    periodLabel(this._offset(), this._nowMs())
  );

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
    const isStale = ageMs > LIVE_STALENESS_LIMIT_MS;
    const time = d.toLocaleTimeString('en-GB', {
      hour: '2-digit', minute: '2-digit', second: '2-digit', timeZone: 'UTC',
    });
    if (isStale) {
      const s = Math.round(ageMs / 1000);
      const m = Math.round(s / 60);
      const h = Math.round(m / 60);
      const age = s < 60 ? `${s}s ago`
        : m < 60 ? `${m}m ago`
        : h < 48 ? `${h}h ago`
        : `${Math.round(h / 24)}d ago`;
      return `${time} UTC · stale (${age})`;
    }
    return `${time} UTC`;
  });

  /** True if the last sample is older than LIVE_STALENESS_LIMIT_MS */
  readonly isStale = computed(() => {
    const ts = this.latestSampleMs();
    if (ts === null) return false;
    return this._nowMs() - ts > LIVE_STALENESS_LIMIT_MS;
  });

  // ── Chart computation ────────────────────────────────────────────────────────
  readonly chartData = computed((): ChartOutput => {
    const data   = this._data();
    const offset = this._offset();
    const nowMs  = this._nowMs();
    const view   = this.view();

    const empty: ChartOutput = {
      series: [], gridLines: [], xLabels: [],
      plotLeft: CHART_PAD_LEFT, plotRight: CHART_W - CHART_PAD_RIGHT,
      plotTop:  CHART_PAD_TOP,  plotBottom: CHART_H - CHART_PAD_BOTTOM,
    };

    const providers = Object.keys(data);
    if (providers.length === 0) return empty;

    const dayStartMs = utcDayStart(nowMs, offset);
    const dayEndMs   = dayStartMs + 86_400_000;

    // Determine visible x-window
    let winStartMs: number;
    let winEndMs: number;

    if (view === 'live') {
      // TODO: For now full-day is also shown when no data is within the live window.
      // A future improvement could anchor precisely to the trailing LIVE_WINDOW_MS.
      const latestTs = this.latestSampleMs();
      if (latestTs !== null) {
        const isStale = nowMs - latestTs > LIVE_STALENESS_LIMIT_MS;
        const anchor  = isStale ? latestTs : Math.max(nowMs, latestTs);
        winEndMs   = anchor + LIVE_RIGHT_PAD_MS;
        winStartMs = winEndMs - LIVE_WINDOW_MS;
      } else {
        // No data yet — show the full day so the chart isn't blank
        winStartMs = dayStartMs;
        winEndMs   = dayEndMs;
      }
    } else {
      winStartMs = dayStartMs;
      winEndMs   = dayEndMs;
    }

    const winDurMs = Math.max(winEndMs - winStartMs, 1);

    const plotW  = CHART_W - CHART_PAD_LEFT - CHART_PAD_RIGHT;
    const plotH  = CHART_H - CHART_PAD_TOP  - CHART_PAD_BOTTOM;
    const base   = CHART_PAD_TOP + plotH; // y-coordinate of baseline

    // ── Build raw points per provider ────────────────────────────────────────
    type RawPt = { tsMs: number; gb: number };
    const rawBySeries: { name: string; pts: RawPt[] }[] = providers.map(name => {
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
    }).filter(s => s.pts.length > 0);

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
        for (const p of pts) { if (p.gb > maxGb) maxGb = p.gb; }
      }
    }
    const yMax = niceMax(maxGb);

    // ── Helper: ts → svg-x ───────────────────────────────────────────────────
    const tsToX = (tsMs: number): number =>
      CHART_PAD_LEFT + ((tsMs - winStartMs) / winDurMs) * plotW;

    const gbToY = (gb: number): number =>
      CHART_PAD_TOP + plotH * (1 - Math.min(gb / yMax, 1));

    // ── Build per-provider SVG paths ─────────────────────────────────────────
    const series: ProviderSeries[] = rawBySeries.map(({ name, pts }, idx) => {
      const color = seriesColor(idx);

      // Build {x,y} points
      const plotPts: PlotPoint[] = pts.map(p => ({
        x: tsToX(p.tsMs),
        y: gbToY(p.gb),
      }));

      // Area path: move to first point, line across all, close to baseline
      let areaPath = '';
      if (plotPts.length > 0) {
        const first = plotPts[0];
        const last  = plotPts[plotPts.length - 1];
        areaPath  = `M${first.x},${base} L${first.x},${first.y}`;
        for (let i = 1; i < plotPts.length; i++) {
          areaPath += ` L${plotPts[i].x},${plotPts[i].y}`;
        }
        areaPath += ` L${last.x},${base} Z`;
      }

      // Polyline points string for the top line
      const linePoints = plotPts.map(p => `${p.x},${p.y}`).join(' ');

      return { name, color, points: plotPts, areaPath, linePoints };
    });

    // ── Grid lines ───────────────────────────────────────────────────────────
    const gridLines: GridLine[] = [0.25, 0.5, 0.75, 1.0].map(f => ({
      y:     CHART_PAD_TOP + plotH * (1 - f),
      label: formatGb(f * yMax),
    }));

    // ── X-axis labels (hourly within window) ─────────────────────────────────
    const xLabels: XLabel[] = [];
    const hourMs = 3_600_000;
    const firstHour = Math.ceil(winStartMs / hourMs) * hourMs;
    for (let ts = firstHour; ts <= winEndMs; ts += hourMs) {
      const x = tsToX(ts);
      if (x < CHART_PAD_LEFT || x > CHART_W - CHART_PAD_RIGHT) continue;
      const d = new Date(ts);
      const label = `${String(d.getUTCHours()).padStart(2, '0')}:00`;
      xLabels.push({ x, label });
    }
    // Thin out if too many
    const maxLabels = 8;
    const step = Math.max(1, Math.ceil(xLabels.length / maxLabels));
    const filteredLabels = xLabels.filter((_, i) => i % step === 0);

    return {
      series,
      gridLines,
      xLabels: filteredLabels,
      plotLeft:   CHART_PAD_LEFT,
      plotRight:  CHART_W - CHART_PAD_RIGHT,
      plotTop:    CHART_PAD_TOP,
      plotBottom: CHART_H - CHART_PAD_BOTTOM,
    };
  });

  // ── Derived: has any data ────────────────────────────────────────────────────
  readonly hasData = computed(() => {
    const data = this._data();
    return Object.values(data).some(arr => arr.length > 0);
  });

  // ── ngOnChanges bridge ──────────────────────────────────────────────────────
  ngOnChanges(changes: SimpleChanges): void {
    if (changes['vramDataByProvider']) this._data.set(this.vramDataByProvider);
    if (changes['vramDayOffset'])      this._offset.set(this.vramDayOffset);
    if (changes['nowMs'])              this._nowMs.set(this.nowMs);
  }

  // ── Day-nav handlers ────────────────────────────────────────────────────────
  navPrev(): void {
    this.vramDayOffsetChange.emit(this.vramDayOffset + 1);
  }

  navNext(): void {
    if (this.vramDayOffset === 0) return;
    this.vramDayOffsetChange.emit(this.vramDayOffset - 1);
  }

  setView(v: string): void {
    this.view.set(v as ViewMode);
  }
}
