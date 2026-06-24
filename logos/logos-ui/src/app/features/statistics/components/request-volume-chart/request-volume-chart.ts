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
import { SegmentedSwitchComponent } from '../segmented-switch/segmented-switch';
import { CHART_ROLE, seriesColor } from '../../statistics.constants';

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

function formatTimestamp(ts: number): string {
  const d = new Date(ts);
  return d.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit', hour12: true });
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

export interface TooltipState {
  seriesName: string;
  value: number;
  timeLabel: string;
  x: number;
  y: number;
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

  // ── Internal state ───────────────────────────────────────────────────────
  readonly mode = signal<ViewMode>('provider');

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
      const timeLabel = formatTimestamp(ts);
      let stacks: BucketStack = [];

      if (mode === 'provider') {
        const cVal = cloud[i]?.value ?? 0;
        const lVal = local[i]?.value ?? 0;
        if (cVal > 0)
          stacks.push({ key: 'cloud', label: 'Cloud', color: CHART_ROLE.cloud, value: cVal });
        if (lVal > 0)
          stacks.push({ key: 'local', label: 'Local', color: CHART_ROLE.local, value: lVal });
      } else {
        const modelIds = Object.keys(modelMap);
        modelIds.forEach((id, idx) => {
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

    // Build total polyline (provider mode only)
    const totalPolyline: PolylinePoint[] = total.map((p, i) => ({
      x: CHART_PAD_LEFT + i * slotW + slotW / 2,
      y: CHART_PAD_TOP + plotH * (1 - Math.min(p.value / maxVal, 1)),
    }));

    // Grid lines
    const gridLines = [0.25, 0.5, 0.75, 1.0].map((f) => ({
      y: CHART_PAD_TOP + plotH * (1 - f),
      label: formatCount(f * maxVal),
    }));

    // X-axis labels
    const every = Math.max(1, Math.ceil(n / 8));
    const xLabels = buckets
      .filter((_, i) => i % every === 0)
      .map((b, fi) => ({
        x: CHART_PAD_LEFT + fi * every * slotW + slotW / 2,
        label: b.timeLabel,
      }));

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

  // ── Tooltip ─────────────────────────────────────────────────────────────
  tooltipState = signal<TooltipState | null>(null);

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

  // ── Total-line polyline points string ───────────────────────────────────
  readonly polylinePoints = computed(() => {
    const pts = this.chartData().totalPolyline;
    if (pts.length < 2) return '';
    return pts.map((p) => `${p.x},${p.y}`).join(' ');
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

  // ── Tooltip handlers ─────────────────────────────────────────────────────
  showTooltip(rect: BarSegment, event: MouseEvent): void {
    if (this.isDragging) return;
    const svgEl = (event.currentTarget as Element).closest('svg') as SVGSVGElement;
    const wrapEl = svgEl?.parentElement;
    if (!wrapEl) return;
    const wrapRect = wrapEl.getBoundingClientRect();
    this.tooltipState.set({
      seriesName: rect.label,
      value: rect.value,
      timeLabel: rect.timeLabel,
      x: event.clientX - wrapRect.left,
      y: event.clientY - wrapRect.top - 40,
    });
  }

  hideTooltip(): void {
    this.tooltipState.set(null);
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
    this.tooltipState.set(null);
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
    this.hideTooltip();
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
    if (!svg) return null;
    const rect = svg.getBoundingClientRect();
    const svgW = rect.width;
    if (svgW === 0) return null;
    // Map clientX → viewBox x, then to fraction within plot area
    const scaleX = CHART_W / svgW;
    const vbX = (event.clientX - rect.left) * scaleX;
    const plotW = CHART_W - CHART_PAD_LEFT - CHART_PAD_RIGHT;
    const frac = (vbX - CHART_PAD_LEFT) / plotW;
    return Math.max(0, Math.min(1, frac));
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
