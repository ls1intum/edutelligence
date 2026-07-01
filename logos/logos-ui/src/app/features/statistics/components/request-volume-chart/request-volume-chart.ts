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

export interface ChartTooltip {
  /** Cursor viewport coordinates; the host clamps the box inside the viewport. */
  x: number;
  y: number;
  timeLabel: string;
  rows: { label: string; value: number; color: string }[];
}
import { SegmentedSwitchComponent } from '../segmented-switch/segmented-switch';
import { CHART_ROLE, seriesColor } from '../../statistics.constants';
import { nearestIndex, pointerPlotFrac } from '../chart-interaction.util';

export interface DataPoint {
  value: number;
  timestamp: number;
}

// ── SVG geometry constants ───────────────────────────────────────────────────
const CHART_W = 1000;
const CHART_H = 200;
const CHART_PAD_LEFT = 44;
const CHART_PAD_BOTTOM = 24;
const CHART_PAD_TOP = 8;
const CHART_PAD_RIGHT = 8;

function niceMax(rawMax: number): number {
  if (rawMax === 0) return 10;
  const mag = Math.pow(10, Math.floor(Math.log10(rawMax)));
  const n = rawMax / mag;
  const nice = n <= 1.5 ? 1.5 : n <= 3 ? 3 : n <= 7 ? 7 : 10;
  return nice * mag;
}

function formatCount(v: number): string {
  if (v >= 1_000_000) return `${(v / 1_000_000).toFixed(1)}M`;
  if (v >= 1_000) return `${(v / 1_000).toFixed(0)}k`;
  return String(Math.round(v));
}

function formatTimestamp(ts: number, spanMs: number): string {
  const d = new Date(ts);
  if (spanMs <= 2 * 86_400_000) {
    return d.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', hour12: false });
  }
  if (spanMs <= 32 * 86_400_000) {
    return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
  }
  return d.toLocaleDateString('en-US', { month: 'short', year: 'numeric' });
}

// ── Internal chart types ─────────────────────────────────────────────────────

export interface BarSegment {
  x: number;
  y: number;
  width: number;
  height: number;
  color: string;
  isTop: boolean;
  label: string; // series name
  value: number;
  timeLabel: string;
  seriesKey: string;
}

export interface PolylinePoint {
  x: number;
  y: number;
}

export interface ChartData {
  rects: BarSegment[];
  totalPolyline: PolylinePoint[];
  gridLines: Array<{ y: number; label: string }>;
  xLabels: Array<{ x: number; label: string }>;
  plotLeft: number;
  plotRight: number;
  plotTop: number;
  plotBottom: number;
}

export interface LegendItem {
  key: string;
  label: string;
  color: string;
}

type ViewMode = 'provider' | 'model';

@Component({
  selector: 'app-stats-request-volume-chart',
  standalone: true,
  imports: [SegmentedSwitchComponent],
  templateUrl: './request-volume-chart.html',
  changeDetection: ChangeDetectionStrategy.Eager,
  styleUrl: './request-volume-chart.scss',
})
export class RequestVolumeChartComponent implements OnChanges {
  // ── Inputs ──────────────────────────────────────────────────────────────
  @Input() totalLineData: DataPoint[] = [];
  @Input() cloudLineData: DataPoint[] = [];
  @Input() localLineData: DataPoint[] = [];
  @Input() modelSeriesMap: Record<string, DataPoint[]> = {};
  @Input() modelLabelById: Record<string, string> = {};
  @Input() modelColors: Record<string, string> = {};
  @Input() resetZoomTrigger = 0;

  // ── Outputs ─────────────────────────────────────────────────────────────
  @Output() zoom = new EventEmitter<{ start: Date; end: Date }>();
  @Output() tooltipChange = new EventEmitter<ChartTooltip | null>();

  // ── Internal state ───────────────────────────────────────────────────────
  readonly mode = signal<ViewMode>('provider');
  readonly hiddenSeries = signal<Set<string>>(new Set());

  toggleSeries(key: string): void {
    const next = new Set(this.hiddenSeries());
    next.has(key) ? next.delete(key) : next.add(key);
    this.hiddenSeries.set(next);
  }

  isHidden(key: string): boolean {
    return this.hiddenSeries().has(key);
  }

  /** Whether the chart has any underlying data. Drives the empty-state independently
   *  of legend toggles, so hiding every series never fakes a "no data" message. */
  readonly hasData = computed(() => this._total().length > 0);

  // Signals for inputs (used in computed so they react to changes)
  private readonly _total = signal<DataPoint[]>([]);
  private readonly _cloud = signal<DataPoint[]>([]);
  private readonly _local = signal<DataPoint[]>([]);
  private readonly _modelMap = signal<Record<string, DataPoint[]>>({});
  private readonly _modelLbl = signal<Record<string, string>>({});
  private readonly _modelClr = signal<Record<string, string>>({});

  // ── Mode switch options ─────────────────────────────────────────────────
  readonly modeOptions = [
    { value: 'provider', label: 'By provider' },
    { value: 'model', label: 'By model' },
  ];

  // ── Chart layout constants (exposed for template) ───────────────────────
  readonly CHART_W = CHART_W;
  readonly CHART_H = CHART_H;
  readonly CHART_PAD_LEFT = CHART_PAD_LEFT;
  readonly CHART_PAD_BOTTOM = CHART_PAD_BOTTOM;
  readonly CHART_PAD_TOP = CHART_PAD_TOP;
  readonly CHART_PAD_RIGHT = CHART_PAD_RIGHT;

  // ── Computed chart data ─────────────────────────────────────────────────
  readonly chartData = computed((): ChartData => {
    const total = this._total();
    const cloud = this._cloud();
    const local = this._local();
    const modelMap = this._modelMap();
    const modelLbl = this._modelLbl();
    const modelClr = this._modelClr();
    const mode = this.mode();
    const hidden = this.hiddenSeries();

    const n = total.length;
    const empty: ChartData = {
      rects: [],
      totalPolyline: [],
      gridLines: [],
      xLabels: [],
      plotLeft: CHART_PAD_LEFT,
      plotRight: CHART_W - CHART_PAD_RIGHT,
      plotTop: CHART_PAD_TOP,
      plotBottom: CHART_H - CHART_PAD_BOTTOM,
    };
    if (n === 0) return empty;

    const spanMs = n > 1 ? total[n - 1].timestamp - total[0].timestamp : 0;

    const plotW = CHART_W - CHART_PAD_LEFT - CHART_PAD_RIGHT;
    const plotH = CHART_H - CHART_PAD_TOP - CHART_PAD_BOTTOM;
    const slotW = plotW / n;
    const barW = Math.max(4, Math.min(20, slotW * 0.65));
    const barBase = CHART_PAD_TOP + plotH;

    // Build per-bucket stacks
    type BucketStack = { key: string; label: string; color: string; value: number }[];
    const buckets: { ts: number; timeLabel: string; stacks: BucketStack }[] = [];

    for (let i = 0; i < n; i++) {
      const ts = total[i].timestamp;
      const timeLabel = formatTimestamp(ts, spanMs);
      let stacks: BucketStack = [];

      if (mode === 'provider') {
        const cVal = cloud[i]?.value ?? 0;
        const lVal = local[i]?.value ?? 0;
        if (cVal > 0 && !hidden.has('cloud'))
          stacks.push({ key: 'cloud', label: 'Cloud', color: CHART_ROLE.cloud, value: cVal });
        if (lVal > 0 && !hidden.has('local'))
          stacks.push({ key: 'local', label: 'Local', color: CHART_ROLE.local, value: lVal });
      } else {
        const modelIds = Object.keys(modelMap);
        modelIds.forEach((id, idx) => {
          if (hidden.has(id)) return;
          const pts = modelMap[id];
          const val = pts[i]?.value ?? 0;
          if (val > 0) {
            const color = modelClr[id] ?? seriesColor(idx);
            const label = modelLbl[id] ?? id;
            stacks.push({ key: id, label, color, value: val });
          }
        });
      }
      buckets.push({ ts, timeLabel, stacks });
    }

    // Compute max stacked value
    const stackedTotals = buckets.map((b) => b.stacks.reduce((s, seg) => s + seg.value, 0));
    const rawMax = Math.max(...stackedTotals, ...total.map((p) => p.value));
    const maxVal = niceMax(rawMax);

    // Build rects
    const rects: BarSegment[] = [];
    for (let i = 0; i < buckets.length; i++) {
      const b = buckets[i];
      const centerX = CHART_PAD_LEFT + i * slotW + slotW / 2;
      const barX = centerX - barW / 2;
      let cumY = barBase;

      const segRects: BarSegment[] = [];
      for (const seg of b.stacks) {
        const h = (seg.value / maxVal) * plotH;
        if (h < 0.5) continue;
        cumY -= h;
        segRects.push({
          x: barX,
          y: cumY,
          width: barW,
          height: h,
          color: seg.color,
          isTop: false,
          label: seg.label,
          value: seg.value,
          timeLabel: b.timeLabel,
          seriesKey: seg.key,
        });
      }
      if (segRects.length > 0) segRects[segRects.length - 1].isTop = true;
      rects.push(...segRects);
    }

    // Build total polyline (provider mode only, unless hidden)
    const totalPolyline: PolylinePoint[] = hidden.has('total') ? [] : total.map((p, i) => ({
      x: CHART_PAD_LEFT + i * slotW + slotW / 2,
      y: CHART_PAD_TOP + plotH * (1 - Math.min(p.value / maxVal, 1)),
    }));

    // Grid lines
    const gridLines = [0.25, 0.5, 0.75, 1.0].map((f) => ({
      y: CHART_PAD_TOP + plotH * (1 - f),
      label: formatCount(f * maxVal),
    }));

    // X-axis labels
    // For sub-2-day spans: evenly space up to 8 time labels.
    // For wider spans: label on day (or month for 6m/year) boundaries only.
    let xLabels: Array<{ x: number; label: string }>;
    if (spanMs <= 2 * 86_400_000) {
      const every = Math.max(1, Math.ceil(n / 8));
      xLabels = buckets
        .filter((_, i) => i % every === 0)
        .map((b, fi) => ({
          x: CHART_PAD_LEFT + fi * every * slotW + slotW / 2,
          label: b.timeLabel,
        }));
    } else {
      // Emit a label whenever the day (or month for 6m+) boundary changes.
      const boundaryKey = (ts: number) => {
        const d = new Date(ts);
        return spanMs <= 32 * 86_400_000
          ? `${d.getFullYear()}-${d.getMonth()}-${d.getDate()}`
          : `${d.getFullYear()}-${d.getMonth()}`;
      };
      let lastKey = '';
      xLabels = [];
      buckets.forEach((b, i) => {
        const key = boundaryKey(b.ts);
        if (key !== lastKey) {
          lastKey = key;
          xLabels.push({ x: CHART_PAD_LEFT + i * slotW + slotW / 2, label: b.timeLabel });
        }
      });
      // Thin out if too crowded (keep at most 8 labels).
      if (xLabels.length > 8) {
        const step = Math.ceil(xLabels.length / 8);
        xLabels = xLabels.filter((_, i) => i % step === 0);
      }
    }

    return {
      rects,
      totalPolyline,
      gridLines,
      xLabels,
      plotLeft: CHART_PAD_LEFT,
      plotRight: CHART_W - CHART_PAD_RIGHT,
      plotTop: CHART_PAD_TOP,
      plotBottom: CHART_H - CHART_PAD_BOTTOM,
    };
  });

  // ── Legend ───────────────────────────────────────────────────────────────
  readonly legendItems = computed((): LegendItem[] => {
    const mode = this.mode();
    const modelMap = this._modelMap();
    const modelLbl = this._modelLbl();
    const modelClr = this._modelClr();

    if (mode === 'model') {
      return Object.keys(modelMap).map((id, idx) => ({
        key: id,
        label: modelLbl[id] ?? id,
        color: modelClr[id] ?? seriesColor(idx),
      }));
    }
    return [
      { key: 'cloud', label: 'Cloud', color: CHART_ROLE.cloud },
      { key: 'local', label: 'Local', color: CHART_ROLE.local },
      { key: 'total', label: 'Total', color: CHART_ROLE.total },
    ];
  });

  // ── Crosshair / unified hover tooltip ───────────────────────────────────
  readonly hoverIndex = signal<number | null>(null);

  readonly crosshair = computed((): {
    x: number;
    rows: { label: string; value: number; color: string }[];
    timeLabel: string;
  } | null => {
    const i = this.hoverIndex();
    if (i === null) return null;
    const total = this._total();
    if (i < 0 || i >= total.length) return null;
    const mode = this.mode();
    const rows: { label: string; value: number; color: string }[] = [];
    const hidden = this.hiddenSeries();
    if (mode === 'provider') {
      const c = this._cloud()[i]?.value ?? 0;
      const l = this._local()[i]?.value ?? 0;
      if (!hidden.has('cloud')) rows.push({ label: 'Cloud', value: c, color: CHART_ROLE.cloud });
      if (!hidden.has('local')) rows.push({ label: 'Local', value: l, color: CHART_ROLE.local });
    } else {
      const map = this._modelMap();
      const lbl = this._modelLbl();
      const clr = this._modelClr();
      Object.keys(map).forEach((id, idx) => {
        if (hidden.has(id)) return;
        const val = map[id][i]?.value ?? 0;
        if (val > 0) rows.push({ label: lbl[id] ?? id, value: val, color: clr[id] ?? seriesColor(idx) });
      });
    }
    if (!hidden.has('total')) rows.push({ label: 'Total', value: total[i].value, color: CHART_ROLE.total });
    const plotW = CHART_W - CHART_PAD_LEFT - CHART_PAD_RIGHT;
    const slotW = plotW / total.length;
    const x = CHART_PAD_LEFT + i * slotW + slotW / 2;
    const spanMs = total.length > 1 ? total[total.length - 1].timestamp - total[0].timestamp : 0;
    return { x, rows, timeLabel: formatTimestamp(total[i].timestamp, spanMs) };
  });

  // ── Drag-to-zoom state ───────────────────────────────────────────────────
  private isDragging = false;
  private dragStartFrac = 0;
  private dragEndFrac = 0;

  /** SVG x-coordinate of the selection rectangle start (in viewBox units) */
  zoomSelX = signal(0);
  /** Width of selection rectangle (in viewBox units) */
  zoomSelW = signal(0);
  /** Whether a drag is in progress */
  isDraggingSig = signal(false);

  // ── Total-line smoothed path ─────────────────────────────────────────────
  // Builds a smooth SVG path through the total points using a Catmull-Rom
  // spline converted to cubic Béziers (tension 0 = standard Catmull-Rom).
  readonly totalLinePath = computed(() => {
    const pts = this.chartData().totalPolyline;
    if (pts.length < 2) return '';
    if (pts.length === 2) return `M${pts[0].x},${pts[0].y} L${pts[1].x},${pts[1].y}`;

    let d = `M${pts[0].x},${pts[0].y}`;
    for (let i = 0; i < pts.length - 1; i++) {
      const p0 = pts[i - 1] ?? pts[i];
      const p1 = pts[i];
      const p2 = pts[i + 1];
      const p3 = pts[i + 2] ?? p2;

      const c1x = p1.x + (p2.x - p0.x) / 6;
      const c1y = p1.y + (p2.y - p0.y) / 6;
      const c2x = p2.x - (p3.x - p1.x) / 6;
      const c2y = p2.y - (p3.y - p1.y) / 6;

      d += ` C${c1x},${c1y} ${c2x},${c2y} ${p2.x},${p2.y}`;
    }
    return d;
  });

  ngOnChanges(changes: SimpleChanges): void {
    if (changes['totalLineData']) this._total.set(this.totalLineData);
    if (changes['cloudLineData']) this._cloud.set(this.cloudLineData);
    if (changes['localLineData']) this._local.set(this.localLineData);
    if (changes['modelSeriesMap']) this._modelMap.set(this.modelSeriesMap);
    if (changes['modelLabelById']) this._modelLbl.set(this.modelLabelById);
    if (changes['modelColors']) this._modelClr.set(this.modelColors);

    if (changes['resetZoomTrigger'] && !changes['resetZoomTrigger'].firstChange) {
      this.clearZoomSelection();
    }
  }

  setMode(v: string): void {
    this.mode.set(v as ViewMode);
  }

  // ── Drag-to-zoom handlers ─────────────────────────────────────────────────
  onMouseDown(event: MouseEvent): void {
    // Only primary button
    if (event.button !== 0) return;
    const frac = this.eventToPlotFrac(event);
    if (frac === null) return;
    event.preventDefault();
    this.isDragging = true;
    this.dragStartFrac = frac;
    this.dragEndFrac = frac;
    this.updateSelRect(frac, frac);
    this.isDraggingSig.set(true);
  }

  onMouseMove(event: MouseEvent): void {
    if (!this.isDragging) return;
    const frac = this.eventToPlotFrac(event);
    if (frac === null) return;
    this.dragEndFrac = frac;
    this.updateSelRect(this.dragStartFrac, frac);
  }

  onMouseUp(event: MouseEvent): void {
    if (!this.isDragging) return;
    this.isDragging = false;
    this.isDraggingSig.set(false);

    const frac = this.eventToPlotFrac(event);
    if (frac !== null) this.dragEndFrac = frac;

    const startFrac = Math.min(this.dragStartFrac, this.dragEndFrac);
    const endFrac = Math.max(this.dragStartFrac, this.dragEndFrac);
    const span = endFrac - startFrac;

    if (span >= 0.02 && this.totalLineData.length >= 2) {
      const firstTs = this.totalLineData[0].timestamp;
      const lastTs = this.totalLineData[this.totalLineData.length - 1].timestamp;
      const dur = lastTs - firstTs;
      const tStart = firstTs + startFrac * dur;
      const tEnd = firstTs + endFrac * dur;
      this.zoom.emit({ start: new Date(tStart), end: new Date(tEnd) });
    }

    this.clearZoomSelection();
  }

  onMouseLeave(): void {
    if (this.isDragging) {
      this.isDragging = false;
      this.isDraggingSig.set(false);
      this.clearZoomSelection();
    }
  }

  // ── Crosshair / unified hover handlers ────────────────────────────────────
  onPlotMove(event: MouseEvent): void {
    if (this.isDraggingSig()) return;
    const frac = this.eventToPlotFrac(event);
    const n = this._total().length;
    const idx = frac === null ? null : nearestIndex(frac, n);
    this.hoverIndex.set(idx);
    const ch = this.crosshair();
    if (ch && idx !== null) {
      this.tooltipChange.emit({ x: event.clientX, y: event.clientY, timeLabel: ch.timeLabel, rows: ch.rows });
    } else {
      this.tooltipChange.emit(null);
    }
  }

  onPlotLeave(): void {
    this.hoverIndex.set(null);
    this.tooltipChange.emit(null);
    this.onMouseLeave();
  }

  // ── Helpers ───────────────────────────────────────────────────────────────

  roundedTopPath(r: BarSegment): string {
    const rad = Math.min(3, r.width / 2);
    return (
      `M${r.x},${r.y + rad} ` +
      `Q${r.x},${r.y} ${r.x + rad},${r.y} ` +
      `L${r.x + r.width - rad},${r.y} ` +
      `Q${r.x + r.width},${r.y} ${r.x + r.width},${r.y + rad} ` +
      `L${r.x + r.width},${r.y + r.height} ` +
      `L${r.x},${r.y + r.height} Z`
    );
  }

  formatValue(v: number): string {
    return formatCount(v) + ' req';
  }

  private eventToPlotFrac(event: MouseEvent): number | null {
    const svgEl = event.currentTarget as Element;
    const svg = (svgEl.tagName === 'svg' ? svgEl : svgEl.closest('svg')) as SVGSVGElement | null;
    return pointerPlotFrac(event, svg, CHART_W, CHART_PAD_LEFT, CHART_PAD_RIGHT);
  }

  private updateSelRect(startFrac: number, endFrac: number): void {
    const plotW = CHART_W - CHART_PAD_LEFT - CHART_PAD_RIGHT;
    const f0 = Math.min(startFrac, endFrac);
    const f1 = Math.max(startFrac, endFrac);
    this.zoomSelX.set(CHART_PAD_LEFT + f0 * plotW);
    this.zoomSelW.set((f1 - f0) * plotW);
  }

  private clearZoomSelection(): void {
    this.zoomSelX.set(0);
    this.zoomSelW.set(0);
    this.isDraggingSig.set(false);
    this.isDragging = false;
  }
}
