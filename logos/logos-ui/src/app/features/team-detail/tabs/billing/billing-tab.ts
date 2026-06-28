import {
  Component,
  Input,
  signal,
  computed,
  effect,
  inject,
  viewChild,
  ElementRef,
  ChangeDetectionStrategy,
} from '@angular/core';
import { BillingService, KeyBudgetBucket } from '../../../../core/services/billing.service';
import { ErrorMessageComponent } from '../../../../shared/components/error-message/error-message';
import { DataTableComponent } from '../../../../shared/components/data-table/data-table';
import {
  TimePreset,
  calendarRange,
  periodLabel as periodLabelFn,
  VS_LABEL,
  AVG_UNIT,
} from '../../../../shared/utils/time-range';
import { TimeRangeBarComponent } from '../../../../shared/components/time-range-bar/time-range-bar';

const MICRO = 100_000_000;

function formatBucketLabel(ts: string, preset: TimePreset): string {
  const d = new Date(ts);
  switch (preset) {
    case 'day':
      return d.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', hour12: false });
    case 'week':
    case 'month':
    case '6m':
      return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
    case 'year':
      return d.toLocaleDateString('en-US', { month: 'short', year: 'numeric' });
  }
}

function niceMax(v: number): number {
  if (v === 0) return 1;
  const mag = Math.pow(10, Math.floor(Math.log10(v)));
  const n = v / mag;
  return (n <= 1.5 ? 1.5 : n <= 3 ? 3 : n <= 7 ? 7 : 10) * mag;
}

function formatCostShort(mc: number): string {
  const d = mc / MICRO;
  if (d >= 1000) return `$${(d / 1000).toFixed(1)}k`;
  if (d >= 1) return `$${d.toFixed(0)}`;
  return `$${d.toFixed(2)}`;
}

export interface KeyRow {
  id: number;
  name: string;
  cost: number;
  prevCost: number;
  pct: number;
  trendPct: number | null;
}

interface BucketCol {
  centerX: number;
  label: string;
  rows: Array<{ keyName: string; color: string; cost: number }>;
  total: number;
}

const KEY_COLORS = ['#7c3aed', '#06b6d4', '#22c55e', '#f59e0b', '#ec4899', '#f97316'] as const;

interface SvgRect {
  x: number;
  y: number;
  width: number;
  height: number;
  keyIdx: number;
  isTop: boolean;
}

interface ChartOutput {
  rects: SvgRect[];
  gridLines: Array<{ y: number; label: string }>;
  xLabels: Array<{ x: number; label: string }>;
  buckets: BucketCol[];
  plotTop: number;
  plotBottom: number;
  barW: number;
}

@Component({
  selector: 'app-billing-tab',
  standalone: true,
  imports: [ErrorMessageComponent, TimeRangeBarComponent, DataTableComponent],
  templateUrl: './billing-tab.html',
  changeDetection: ChangeDetectionStrategy.Eager,
  styleUrl: './billing-tab.scss',
})
export class BillingTabComponent {
  @Input() teamId!: number;

  private billing = inject(BillingService);

  preset = signal<TimePreset>('month');
  offset = signal(0);

  loading = signal(true);
  error = signal(false);

  currentBuckets = signal<KeyBudgetBucket[]>([]);
  previousBuckets = signal<KeyBudgetBucket[]>([]);

  hoverBucket = signal<number | null>(null);
  tooltipPos = signal<{ left: number; top: number } | null>(null);

  private readonly tooltipEl = viewChild<ElementRef<HTMLDivElement>>('tooltipEl');

  readonly CHART_W = 900;
  readonly CHART_H = 150;
  readonly PAD_L = 44;
  readonly PAD_B = 20;
  readonly PAD_T = 6;
  readonly PAD_R = 8;

  private ranges = computed(() => calendarRange(this.preset(), this.offset()));

  periodLabel = computed(() =>
    periodLabelFn(this.preset(), this.offset(), this.ranges()),
  );

  vsLabel = computed(() => VS_LABEL[this.preset()]);

  breakdownColumns = computed(() => ['KEY', 'SPEND', '% OF TOTAL', this.vsLabel().toUpperCase()]);
  avgUnit = computed(() => AVG_UNIT[this.preset()]);
  trendIsUp = computed(() => (this.trendPct() ?? 0) >= 0);

  avgDivisor = computed((): number => {
    const { currStart, currEnd } = this.ranges();
    switch (this.preset()) {
      case 'day':
        return 24;
      case 'week':
        return 7;
      case 'month':
        return Math.round((currEnd.getTime() - currStart.getTime()) / 86_400_000);
      case '6m':
        return 6;
      case 'year':
        return 12;
    }
  });

  currentTotal = computed(() => this.currentBuckets().reduce((s, b) => s + b.cost_micro_cents, 0));
  previousTotal = computed(() =>
    this.previousBuckets().reduce((s, b) => s + b.cost_micro_cents, 0),
  );

  trendPct = computed((): number | null => {
    const prev = this.previousTotal();
    if (prev === 0) return null;
    return ((this.currentTotal() - prev) / prev) * 100;
  });

  keys = computed((): KeyRow[] => {
    const curr = this.currentBuckets();
    const prev = this.previousBuckets();
    const total = this.currentTotal();

    const map = new Map<number, { name: string; cost: number }>();
    for (const b of curr) {
      const ex = map.get(b.api_key_id);
      if (ex) ex.cost += b.cost_micro_cents;
      else map.set(b.api_key_id, { name: b.api_key_name, cost: b.cost_micro_cents });
    }
    const prevMap = new Map<number, number>();
    for (const b of prev)
      prevMap.set(b.api_key_id, (prevMap.get(b.api_key_id) ?? 0) + b.cost_micro_cents);

    return [...map.entries()]
      .sort(([, a], [, b]) => b.cost - a.cost)
      .map(([id, { name, cost }]) => {
        const prevCost = prevMap.get(id) ?? 0;
        return {
          id,
          name,
          cost,
          prevCost,
          pct: total > 0 ? (cost / total) * 100 : 0,
          trendPct: prevCost > 0 ? ((cost - prevCost) / prevCost) * 100 : null,
        };
      });
  });

  chartData = computed((): ChartOutput => {
    const buckets = this.currentBuckets();
    const keys = this.keys();
    const preset = this.preset();
    if (buckets.length === 0 || keys.length === 0) {
      return { rects: [], gridLines: [], xLabels: [], buckets: [], plotTop: 0, plotBottom: 0, barW: 0 };
    }

    const times = [...new Set(buckets.map((b) => b.bucket_ts))].sort();
    const n = times.length;

    const bars = times.map((ts) => {
      const slice = buckets.filter((b) => b.bucket_ts === ts);
      let total = 0;
      const stacks = keys
        .map((k, idx) => {
          const v = slice.find((b) => b.api_key_id === k.id)?.cost_micro_cents ?? 0;
          total += v;
          return { keyIdx: idx, keyName: k.name, value: v };
        })
        .filter((s) => s.value > 0);
      return { ts, label: formatBucketLabel(ts, preset), stacks, total };
    });

    const rawMax = Math.max(...bars.map((b) => b.total));
    const maxVal = niceMax(rawMax);
    const plotW = this.CHART_W - this.PAD_L - this.PAD_R;
    const plotH = this.CHART_H - this.PAD_T - this.PAD_B;
    const slotW = plotW / n;
    const barW = Math.max(5, Math.min(24, slotW * 0.65));
    const base = this.PAD_T + plotH;

    const rects: SvgRect[] = [];
    const bucketCols: BucketCol[] = [];

    for (let i = 0; i < bars.length; i++) {
      const bar = bars[i];
      const cx = this.PAD_L + i * slotW + slotW / 2;
      let cumY = base;
      const barRects: SvgRect[] = [];
      for (const seg of bar.stacks) {
        const h = (seg.value / maxVal) * plotH;
        if (h < 0.5) continue;
        cumY -= h;
        barRects.push({ x: cx - barW / 2, y: cumY, width: barW, height: h, keyIdx: seg.keyIdx, isTop: false });
      }
      if (barRects.length > 0) barRects[barRects.length - 1].isTop = true;
      rects.push(...barRects);

      bucketCols.push({
        centerX: cx,
        label: bar.label,
        total: bar.total,
        rows: bar.stacks
          .map((s) => ({ keyName: s.keyName, color: KEY_COLORS[s.keyIdx % KEY_COLORS.length], cost: s.value }))
          .sort((a, b) => b.cost - a.cost),
      });
    }

    const gridLines = [0.25, 0.5, 0.75, 1.0].map((f) => ({
      y: this.PAD_T + plotH * (1 - f),
      label: formatCostShort(f * maxVal),
    }));
    const every = Math.max(1, Math.ceil(n / 8));
    const xLabels = bars
      .filter((_, i) => i % every === 0)
      .map((b, fi) => ({
        x: this.PAD_L + fi * every * slotW + slotW / 2,
        label: b.label,
      }));

    return { rects, gridLines, xLabels, buckets: bucketCols, plotTop: this.PAD_T, plotBottom: base, barW };
  });

  readonly crosshair = computed(() => {
    const idx = this.hoverBucket();
    if (idx === null) return null;
    const col = this.chartData().buckets[idx];
    if (!col || col.rows.length === 0) return null;
    return { x: col.centerX, label: col.label, rows: col.rows, total: col.total };
  });

  constructor() {
    effect(() => {
      const preset = this.preset();
      const offset = this.offset();
      this.hoverBucket.set(null);
      this.tooltipPos.set(null);
      if (this.teamId) this.loadData(preset, offset);
    });
  }

  keyColor(idx: number): string {
    return KEY_COLORS[idx % KEY_COLORS.length];
  }

  formatDollars(mc: number): string {
    return new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' }).format(mc / MICRO);
  }

  formatDollars6(mc: number): string {
    return `$${(mc / MICRO).toFixed(6)}`;
  }

  onPlotMove(event: MouseEvent): void {
    const cd = this.chartData();
    const cols = cd.buckets;
    if (cols.length === 0) { this.onPlotLeave(); return; }
    const svg = (event.currentTarget as Element).closest('svg') as SVGSVGElement | null;
    if (!svg) return;
    const rect = svg.getBoundingClientRect();
    if (rect.width === 0) return;

    const vbX = (event.clientX - rect.left) * (this.CHART_W / rect.width);

    let nearest = 0;
    let bestDist = Infinity;
    for (let i = 0; i < cols.length; i++) {
      const d = Math.abs(vbX - cols[i].centerX);
      if (d < bestDist) { bestDist = d; nearest = i; }
    }
    if (bestDist > cd.barW / 2 + 6) { this.onPlotLeave(); return; }

    this.hoverBucket.set(nearest);
    this.tooltipPos.set(this.clampTooltip(event.clientX, event.clientY));
  }

  onPlotLeave(): void {
    this.hoverBucket.set(null);
    this.tooltipPos.set(null);
  }

  private clampTooltip(clientX: number, clientY: number): { left: number; top: number } {
    const margin = 8;
    const offset = 14;
    const el = this.tooltipEl()?.nativeElement;
    const w = el?.offsetWidth ?? 200;
    const h = el?.offsetHeight ?? 140;
    const vw = typeof window !== 'undefined' ? window.innerWidth : w + clientX + offset + margin;
    const vh = typeof window !== 'undefined' ? window.innerHeight : h + clientY + margin;

    let left = clientX + offset;
    if (left + w + margin > vw) left = clientX - offset - w;
    left = Math.max(margin, Math.min(left, vw - w - margin));

    let top = clientY - 8;
    top = Math.max(margin, Math.min(top, vh - h - margin));

    return { left, top };
  }

  roundedTopPath(r: SvgRect): string {
    const rad = Math.min(3, r.width / 2);
    return `M${r.x},${r.y + rad} Q${r.x},${r.y} ${r.x + rad},${r.y} L${r.x + r.width - rad},${r.y} Q${r.x + r.width},${r.y} ${r.x + r.width},${r.y + rad} L${r.x + r.width},${r.y + r.height} L${r.x},${r.y + r.height} Z`;
  }

  private async loadData(preset: TimePreset, offset: number): Promise<void> {
    const { currStart, currEnd, prevStart, prevEnd } = calendarRange(preset, offset);
    const iso = (d: Date) => d.toISOString();
    this.loading.set(true);
    this.error.set(false);
    this.currentBuckets.set([]);
    this.previousBuckets.set([]);
    this.hoverBucket.set(null);
    this.tooltipPos.set(null);

    try {
      const [current, previous] = await Promise.all([
        this.billing.getKeyBudgetHistory(this.teamId, iso(currStart), iso(currEnd)),
        this.billing.getKeyBudgetHistory(this.teamId, iso(prevStart), iso(prevEnd)),
      ]);
      this.currentBuckets.set(current.buckets);
      this.previousBuckets.set(previous.buckets);
    } catch {
      this.error.set(true);
    } finally {
      this.loading.set(false);
    }
  }
}
