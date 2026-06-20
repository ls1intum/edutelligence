import { Component, Input, signal, computed, effect, inject } from '@angular/core';
import { forkJoin } from 'rxjs';
import { BillingService, KeyBudgetBucket } from '../../../../core/services/billing.service';
import { ErrorMessageComponent } from '../../../../shared/components/error-message/error-message';

export type TimePreset = 'day' | 'week' | 'month' | '6m' | 'year';

function calendarRange(preset: TimePreset, offset: number): { currStart: Date; currEnd: Date; prevStart: Date; prevEnd: Date } {
  const now = new Date();
  let currStart: Date, currEnd: Date, prevStart: Date, prevEnd: Date;
  switch (preset) {
    case 'day': {
      currStart = new Date(now.getFullYear(), now.getMonth(), now.getDate() - offset);
      currEnd   = new Date(currStart.getFullYear(), currStart.getMonth(), currStart.getDate() + 1);
      prevStart = new Date(currStart.getFullYear(), currStart.getMonth(), currStart.getDate() - 1);
      prevEnd   = currStart;
      break;
    }
    case 'week': {
      const dow = now.getDay() === 0 ? 7 : now.getDay();
      const mon = new Date(now.getFullYear(), now.getMonth(), now.getDate() - dow + 1);
      currStart = new Date(mon.getFullYear(), mon.getMonth(), mon.getDate() - offset * 7);
      currEnd   = new Date(currStart.getFullYear(), currStart.getMonth(), currStart.getDate() + 7);
      prevStart = new Date(currStart.getFullYear(), currStart.getMonth(), currStart.getDate() - 7);
      prevEnd   = currStart;
      break;
    }
    case 'month': {
      currStart = new Date(now.getFullYear(), now.getMonth() - offset, 1);
      currEnd   = new Date(currStart.getFullYear(), currStart.getMonth() + 1, 1);
      prevStart = new Date(currStart.getFullYear(), currStart.getMonth() - 1, 1);
      prevEnd   = currStart;
      break;
    }
    case '6m': {
      const endM = new Date(now.getFullYear(), now.getMonth() + 1 - offset * 6, 1);
      currStart = new Date(endM.getFullYear(), endM.getMonth() - 6, 1);
      currEnd   = endM;
      prevStart = new Date(currStart.getFullYear(), currStart.getMonth() - 6, 1);
      prevEnd   = currStart;
      break;
    }
    case 'year': {
      const y = now.getFullYear() - offset;
      currStart = new Date(y, 0, 1); currEnd = new Date(y + 1, 0, 1);
      prevStart = new Date(y - 1, 0, 1); prevEnd = currStart;
      break;
    }
  }
  return { currStart: currStart!, currEnd: currEnd!, prevStart: prevStart!, prevEnd: prevEnd! };
}

const MICRO = 100_000_000;

const VS_LABEL: Record<TimePreset, string> = {
  day:   'vs Yesterday',
  week:  'vs Prev Week',
  month: 'vs Last Month',
  '6m':  'vs Prev 6 Months',
  year:  'vs Last Year',
};

const AVG_UNIT: Record<TimePreset, string> = {
  day:   'avg / hour',
  week:  'avg / day',
  month: 'avg / day',
  '6m':  'avg / month',
  year:  'avg / month',
};

function formatBucketLabel(ts: string, preset: TimePreset): string {
  const d = new Date(ts);
  switch (preset) {
    case 'day':   return d.toLocaleTimeString('en-US', { hour: 'numeric', hour12: true });
    case 'week':  return d.toLocaleDateString('en-US', { weekday: 'short' });
    case 'month': return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
    case '6m':    return d.toLocaleDateString('en-US', { month: 'short' });
    case 'year':  return d.toLocaleDateString('en-US', { month: 'short' });
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
  if (d >= 1)    return `$${d.toFixed(0)}`;
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

interface TooltipState {
  keyName: string;
  cost: number;
  timeLabel: string;
  x: number;
  y: number;
}

const KEY_COLORS = ['#7c3aed', '#06b6d4', '#22c55e', '#f59e0b', '#ec4899', '#f97316'] as const;

interface SvgRect {
  x: number; y: number; width: number; height: number;
  keyIdx: number; isTop: boolean; keyName: string; cost: number; timeLabel: string;
}

interface ChartOutput {
  rects: SvgRect[];
  gridLines: Array<{ y: number; label: string }>;
  xLabels: Array<{ x: number; label: string }>;
}

@Component({
  selector: 'app-billing-tab',
  standalone: true,
  imports: [ErrorMessageComponent],
  templateUrl: './billing-tab.html',
  styleUrl: './billing-tab.scss',
})
export class BillingTabComponent {
  @Input() teamId!: number;

  private billing = inject(BillingService);

  preset = signal<TimePreset>('month');
  offset = signal(0);

  readonly presets: Array<{ value: TimePreset; label: string }> = [
    { value: 'day', label: 'Day' }, { value: 'week', label: 'Week' },
    { value: 'month', label: 'Month' }, { value: '6m', label: '6 Months' },
    { value: 'year', label: 'Year' },
  ];

  loading = signal(true);
  error   = signal(false);

  currentBuckets  = signal<KeyBudgetBucket[]>([]);
  previousBuckets = signal<KeyBudgetBucket[]>([]);

  tooltipState = signal<TooltipState | null>(null);

  readonly CHART_W = 900; readonly CHART_H = 150;
  readonly PAD_L = 44; readonly PAD_B = 20; readonly PAD_T = 6; readonly PAD_R = 8;

  private ranges = computed(() => calendarRange(this.preset(), this.offset()));

  periodLabel = computed(() => {
    const { currStart, currEnd } = this.ranges();
    const preset = this.preset();
    const off    = this.offset();
    switch (preset) {
      case 'day':
        if (off === 0) return 'Today';
        if (off === 1) return 'Yesterday';
        return currStart.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
      case 'week': {
        const end = new Date(currEnd.getTime() - 86400000);
        return `${currStart.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })} - ${end.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })}`;
      }
      case 'month': return currStart.toLocaleDateString('en-US', { month: 'long', year: 'numeric' });
      case '6m': {
        const s = currStart.toLocaleDateString('en-US', { month: 'short', year: 'numeric' });
        const e = new Date(currEnd.getTime() - 86400000).toLocaleDateString('en-US', { month: 'short', year: 'numeric' });
        return `${s} - ${e}`;
      }
      case 'year': return String(currStart.getFullYear());
    }
  });

  vsLabel    = computed(() => VS_LABEL[this.preset()]);
  avgUnit    = computed(() => AVG_UNIT[this.preset()]);
  trendIsUp  = computed(() => (this.trendPct() ?? 0) >= 0);

  avgDivisor = computed((): number => {
    const { currStart, currEnd } = this.ranges();
    switch (this.preset()) {
      case 'day':   return 24;
      case 'week':  return 7;
      case 'month': return Math.round((currEnd.getTime() - currStart.getTime()) / 86_400_000);
      case '6m':    return 6;
      case 'year':  return 12;
    }
  });

  currentTotal  = computed(() => this.currentBuckets().reduce((s, b) => s + b.cost_micro_cents, 0));
  previousTotal = computed(() => this.previousBuckets().reduce((s, b) => s + b.cost_micro_cents, 0));

  trendPct = computed((): number | null => {
    const prev = this.previousTotal();
    if (prev === 0) return null;
    return ((this.currentTotal() - prev) / prev) * 100;
  });

  keys = computed((): KeyRow[] => {
    const curr  = this.currentBuckets();
    const prev  = this.previousBuckets();
    const total = this.currentTotal();

    const map = new Map<number, { name: string; cost: number }>();
    for (const b of curr) {
      const ex = map.get(b.api_key_id);
      if (ex) ex.cost += b.cost_micro_cents;
      else map.set(b.api_key_id, { name: b.api_key_name, cost: b.cost_micro_cents });
    }
    const prevMap = new Map<number, number>();
    for (const b of prev) prevMap.set(b.api_key_id, (prevMap.get(b.api_key_id) ?? 0) + b.cost_micro_cents);

    return [...map.entries()]
      .sort(([, a], [, b]) => b.cost - a.cost)
      .map(([id, { name, cost }]) => {
        const prevCost = prevMap.get(id) ?? 0;
        return {
          id, name, cost, prevCost,
          pct: total > 0 ? (cost / total) * 100 : 0,
          trendPct: prevCost > 0 ? ((cost - prevCost) / prevCost) * 100 : null,
        };
      });
  });

  chartData = computed((): ChartOutput => {
    const buckets = this.currentBuckets();
    const keys    = this.keys();
    const preset  = this.preset();
    if (buckets.length === 0 || keys.length === 0) return { rects: [], gridLines: [], xLabels: [] };

    const times = [...new Set(buckets.map(b => b.bucket_ts))].sort();
    const n = times.length;

    const bars = times.map(ts => {
      const slice = buckets.filter(b => b.bucket_ts === ts);
      let total = 0;
      const stacks = keys.map((k, idx) => {
        const v = slice.find(b => b.api_key_id === k.id)?.cost_micro_cents ?? 0;
        total += v; return { keyIdx: idx, keyName: k.name, value: v };
      }).filter(s => s.value > 0);
      return { ts, label: formatBucketLabel(ts, preset), stacks, total };
    });

    const rawMax = Math.max(...bars.map(b => b.total));
    const maxVal = niceMax(rawMax);
    const plotW  = this.CHART_W - this.PAD_L - this.PAD_R;
    const plotH  = this.CHART_H - this.PAD_T - this.PAD_B;
    const slotW  = plotW / n;
    const barW   = Math.max(5, Math.min(24, slotW * 0.65));
    const base   = this.PAD_T + plotH;

    const rects: SvgRect[] = [];
    for (let i = 0; i < bars.length; i++) {
      const bar = bars[i];
      const cx  = this.PAD_L + i * slotW + slotW / 2;
      let cumY = base;
      const barRects: SvgRect[] = [];
      for (const seg of bar.stacks) {
        const h = (seg.value / maxVal) * plotH;
        if (h < 0.5) continue;
        cumY -= h;
        barRects.push({ x: cx - barW/2, y: cumY, width: barW, height: h, keyIdx: seg.keyIdx, isTop: false, keyName: seg.keyName, cost: seg.value, timeLabel: bar.label });
      }
      if (barRects.length > 0) barRects[barRects.length - 1].isTop = true;
      rects.push(...barRects);
    }

    const gridLines = [0.25, 0.5, 0.75, 1.0].map(f => ({ y: this.PAD_T + plotH * (1 - f), label: formatCostShort(f * maxVal) }));
    const every = Math.max(1, Math.ceil(n / 8));
    const xLabels = bars.filter((_, i) => i % every === 0).map((b, fi) => ({
      x: this.PAD_L + fi * every * slotW + slotW / 2, label: b.label,
    }));

    return { rects, gridLines, xLabels };
  });

  constructor() {
    effect(() => {
      const preset = this.preset();
      const offset = this.offset();
      if (this.teamId) this.loadData(preset, offset);
    });
  }

  setPreset(p: TimePreset): void { this.preset.set(p); this.offset.set(0); this.tooltipState.set(null); }
  navPrev(): void { this.offset.update(o => o + 1); this.tooltipState.set(null); }
  navNext(): void { if (this.offset() > 0) { this.offset.update(o => o - 1); this.tooltipState.set(null); } }

  keyColor(idx: number): string { return KEY_COLORS[idx % KEY_COLORS.length]; }

  formatDollars(mc: number): string {
    return new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' }).format(mc / MICRO);
  }

  showTooltip(r: SvgRect, event: MouseEvent): void {
    const svgEl  = (event.currentTarget as SVGElement).closest('svg') as SVGSVGElement;
    const wrapEl = svgEl?.parentElement;
    if (!wrapEl) return;
    const wrapRect = wrapEl.getBoundingClientRect();
    this.tooltipState.set({
      keyName:   r.keyName,
      cost:      r.cost,
      timeLabel: r.timeLabel,
      x: event.clientX - wrapRect.left,
      y: event.clientY - wrapRect.top - 56,
    });
  }

  hideTooltip(): void { this.tooltipState.set(null); }

  roundedTopPath(r: SvgRect): string {
    const rad = Math.min(3, r.width / 2);
    return `M${r.x},${r.y+rad} Q${r.x},${r.y} ${r.x+rad},${r.y} L${r.x+r.width-rad},${r.y} Q${r.x+r.width},${r.y} ${r.x+r.width},${r.y+rad} L${r.x+r.width},${r.y+r.height} L${r.x},${r.y+r.height} Z`;
  }

  private loadData(preset: TimePreset, offset: number): void {
    const { currStart, currEnd, prevStart, prevEnd } = calendarRange(preset, offset);
    const iso = (d: Date) => d.toISOString();
    this.loading.set(true);
    this.error.set(false);
    this.currentBuckets.set([]);
    this.previousBuckets.set([]);
    this.tooltipState.set(null);

    forkJoin({
      current:  this.billing.getKeyBudgetHistory(this.teamId, iso(currStart), iso(currEnd)),
      previous: this.billing.getKeyBudgetHistory(this.teamId, iso(prevStart), iso(prevEnd)),
    }).subscribe({
      next: ({ current, previous }) => {
        this.currentBuckets.set(current.buckets);
        this.previousBuckets.set(previous.buckets);
        this.loading.set(false);
      },
      error: () => { this.error.set(true); this.loading.set(false); },
    });
  }
}
