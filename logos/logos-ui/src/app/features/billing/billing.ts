import { Component, computed, effect, inject, signal } from '@angular/core';
import { forkJoin } from 'rxjs';
import { BillingService, BudgetBucket } from '../../core/services/billing.service';
import { ErrorMessageComponent } from '../../shared/components/error-message/error-message';

export type TimePreset = 'day' | 'week' | 'month' | '6m' | 'year';

function calendarRange(preset: TimePreset, offset: number): {
  currStart: Date; currEnd: Date;
  prevStart: Date; prevEnd: Date;
} {
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
      const thisMonday = new Date(now.getFullYear(), now.getMonth(), now.getDate() - dow + 1);
      currStart = new Date(thisMonday.getFullYear(), thisMonday.getMonth(), thisMonday.getDate() - offset * 7);
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
      const endMonth = new Date(now.getFullYear(), now.getMonth() + 1 - offset * 6, 1);
      currStart = new Date(endMonth.getFullYear(), endMonth.getMonth() - 6, 1);
      currEnd   = endMonth;
      prevStart = new Date(currStart.getFullYear(), currStart.getMonth() - 6, 1);
      prevEnd   = currStart;
      break;
    }
    case 'year': {
      const year = now.getFullYear() - offset;
      currStart = new Date(year, 0, 1);
      currEnd   = new Date(year + 1, 0, 1);
      prevStart = new Date(year - 1, 0, 1);
      prevEnd   = currStart;
      break;
    }
  }

  return { currStart: currStart!, currEnd: currEnd!, prevStart: prevStart!, prevEnd: prevEnd! };
}

const AVG_UNIT: Record<TimePreset, string> = {
  day:   'avg / hour',
  week:  'avg / day',
  month: 'avg / day',
  '6m':  'avg / month',
  year:  'avg / month',
};

const VS_LABEL: Record<TimePreset, string> = {
  day:   'vs Yesterday',
  week:  'vs Prev Week',
  month: 'vs Last Month',
  '6m':  'vs Prev 6 Months',
  year:  'vs Last Year',
};

const MICRO_CENTS_PER_DOLLAR = 100_000_000;

const TEAM_COLORS = ['purple', 'cyan', 'green', 'orange', 'pink', 'yellow'] as const;
type TeamColor = typeof TEAM_COLORS[number];

export interface TeamRow {
  id: number;
  name: string;
  colorName: TeamColor;
  cost: number;
  prevCost: number;
  pct: number;
  trendPct: number | null;
}

export interface KeyRow {
  id: number;
  name: string;
  cost: number;
  pct: number;
}

interface SvgRect {
  x: number;
  y: number;
  width: number;
  height: number;
  teamIdx: number;
  isTop: boolean;
  teamName: string;
  cost: number;
  timeLabel: string;
}

export interface TooltipState {
  teamName: string;
  cost: number;
  timeLabel: string;
  x: number;
  y: number;
}

interface ChartOutput {
  rects: SvgRect[];
  gridLines: Array<{ y: number; label: string }>;
  xLabels: Array<{ x: number; label: string }>;
}

function formatBucketLabel(iso: string, preset: TimePreset): string {
  const d = new Date(iso);
  switch (preset) {
    case 'day':   return d.toLocaleTimeString('en-US', { hour: 'numeric', hour12: true });
    case 'week':  return d.toLocaleDateString('en-US', { weekday: 'short' });
    case 'month': return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
    case '6m':    return d.toLocaleDateString('en-US', { month: 'short' });
    case 'year':  return d.toLocaleDateString('en-US', { month: 'short' });
  }
}

function niceMax(rawMax: number): number {
  if (rawMax === 0) return 1;
  const mag = Math.pow(10, Math.floor(Math.log10(rawMax)));
  const n = rawMax / mag;
  const nice = n <= 1.5 ? 1.5 : n <= 3 ? 3 : n <= 7 ? 7 : 10;
  return nice * mag;
}

function formatCostShort(microCents: number): string {
  const d = microCents / MICRO_CENTS_PER_DOLLAR;
  if (d >= 1000) return `$${(d / 1000).toFixed(1)}k`;
  if (d >= 1)    return `$${d.toFixed(0)}`;
  return `$${d.toFixed(2)}`;
}

@Component({
  selector: 'app-billing',
  standalone: true,
  imports: [ErrorMessageComponent],
  templateUrl: './billing.html',
  styleUrl: './billing.scss',
})
export class Billing {
  private billingService = inject(BillingService);

  preset = signal<TimePreset>('month');
  offset = signal(0);

  readonly presets: Array<{ value: TimePreset; label: string }> = [
    { value: 'day',   label: 'Day' },
    { value: 'week',  label: 'Week' },
    { value: 'month', label: 'Month' },
    { value: '6m',    label: '6 Months' },
    { value: 'year',  label: 'Year' },
  ];

  loading = signal(true);
  error   = signal(false);

  currentBuckets  = signal<BudgetBucket[]>([]);
  previousBuckets = signal<BudgetBucket[]>([]);

  expandedTeamId    = signal<number | null>(null);
  keysByTeamId      = signal<Record<number, KeyRow[]>>({});
  keysLoadingTeamId = signal<number | null>(null);
  keysErrorTeamId   = signal<number | null>(null);

  tooltipState = signal<TooltipState | null>(null);

  readonly CHART_W          = 1000;
  readonly CHART_H          = 150;
  readonly CHART_PAD_LEFT   = 44;
  readonly CHART_PAD_BOTTOM = 20;
  readonly CHART_PAD_TOP    = 6;
  readonly CHART_PAD_RIGHT  = 8;

  private ranges = computed(() => calendarRange(this.preset(), this.offset()));

  periodLabel = computed(() => {
    const preset = this.preset();
    const off    = this.offset();
    const { currStart, currEnd } = this.ranges();

    switch (preset) {
      case 'day':
        if (off === 0) return 'Today';
        if (off === 1) return 'Yesterday';
        return currStart.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
      case 'week': {
        const end = new Date(currEnd.getTime() - 86_400_000);
        return `${currStart.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })} - ${end.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })}`;
      }
      case 'month':
        return currStart.toLocaleDateString('en-US', { month: 'long', year: 'numeric' });
      case '6m': {
        const s = currStart.toLocaleDateString('en-US', { month: 'short', year: 'numeric' });
        const e = new Date(currEnd.getTime() - 86_400_000).toLocaleDateString('en-US', { month: 'short', year: 'numeric' });
        return `${s} - ${e}`;
      }
      case 'year':
        return String(currStart.getFullYear());
    }
  });

  vsLabel = computed(() => VS_LABEL[this.preset()]);

  currentTotal = computed(() =>
    this.currentBuckets().reduce((s, b) => s + b.cost_micro_cents, 0)
  );

  previousTotal = computed(() =>
    this.previousBuckets().reduce((s, b) => s + b.cost_micro_cents, 0)
  );

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

  avgUnit = computed(() => AVG_UNIT[this.preset()]);

  trendPct = computed((): number | null => {
    const prev = this.previousTotal();
    const curr = this.currentTotal();
    if (prev === 0) return null;
    return ((curr - prev) / prev) * 100;
  });

  // increase = green (good), decrease = red (bad)
  trendIsUp = computed(() => (this.trendPct() ?? 0) >= 0);

  teams = computed((): TeamRow[] => {
    const curr  = this.currentBuckets();
    const prev  = this.previousBuckets();
    const total = this.currentTotal();

    const teamMap = new Map<number, { name: string; cost: number }>();
    for (const b of curr) {
      const ex = teamMap.get(b.team_id);
      if (ex) ex.cost += b.cost_micro_cents;
      else teamMap.set(b.team_id, { name: b.team_name, cost: b.cost_micro_cents });
    }

    const prevMap = new Map<number, number>();
    for (const b of prev) prevMap.set(b.team_id, (prevMap.get(b.team_id) ?? 0) + b.cost_micro_cents);

    return [...teamMap.entries()]
      .sort(([, a], [, b]) => b.cost - a.cost)
      .map(([id, { name, cost }], idx) => {
        const prevCost = prevMap.get(id) ?? 0;
        return {
          id, name,
          colorName: TEAM_COLORS[idx % TEAM_COLORS.length],
          cost, prevCost,
          pct: total > 0 ? (cost / total) * 100 : 0,
          trendPct: prevCost > 0 ? ((cost - prevCost) / prevCost) * 100 : null,
        };
      });
  });

  chartData = computed((): ChartOutput => {
    const buckets = this.currentBuckets();
    const teams   = this.teams();
    const preset  = this.preset();

    if (buckets.length === 0 || teams.length === 0) {
      return { rects: [], gridLines: [], xLabels: [] };
    }

    const bucketTimes = [...new Set(buckets.map(b => b.bucket_ts))].sort();
    const n = bucketTimes.length;

    const bars = bucketTimes.map(ts => {
      const slice = buckets.filter(b => b.bucket_ts === ts);
      let total = 0;
      const stacks = teams
        .map((t, idx) => {
          const v = slice.find(b => b.team_id === t.id)?.cost_micro_cents ?? 0;
          total += v;
          return { teamIdx: idx, teamName: t.name, value: v };
        })
        .filter(s => s.value > 0);
      return { ts, label: formatBucketLabel(ts, preset), stacks, total };
    });

    const rawMax = Math.max(...bars.map(b => b.total));
    const maxVal = niceMax(rawMax);

    const plotW   = this.CHART_W - this.CHART_PAD_LEFT - this.CHART_PAD_RIGHT;
    const plotH   = this.CHART_H - this.CHART_PAD_TOP - this.CHART_PAD_BOTTOM;
    const slotW   = plotW / n;
    const barW    = Math.max(5, Math.min(24, slotW * 0.65));
    const barBase = this.CHART_PAD_TOP + plotH;

    const rects: SvgRect[] = [];
    for (let i = 0; i < bars.length; i++) {
      const bar     = bars[i];
      const centerX = this.CHART_PAD_LEFT + i * slotW + slotW / 2;
      const barX    = centerX - barW / 2;
      let cumY = barBase;

      const barRects: SvgRect[] = [];
      for (const seg of bar.stacks) {
        const h = (seg.value / maxVal) * plotH;
        if (h < 0.5) continue;
        cumY -= h;
        barRects.push({
          x: barX, y: cumY, width: barW, height: h,
          teamIdx: seg.teamIdx, isTop: false,
          teamName: seg.teamName, cost: seg.value, timeLabel: bar.label,
        });
      }
      if (barRects.length > 0) barRects[barRects.length - 1].isTop = true;
      rects.push(...barRects);
    }

    const gridLines = [0.25, 0.5, 0.75, 1.0].map(f => ({
      y:     this.CHART_PAD_TOP + plotH * (1 - f),
      label: formatCostShort(f * maxVal),
    }));

    const every = Math.max(1, Math.ceil(n / 8));
    const xLabels = bars
      .filter((_, i) => i % every === 0)
      .map((b, fi) => ({
        x: this.CHART_PAD_LEFT + (fi * every) * slotW + slotW / 2,
        label: b.label,
      }));

    return { rects, gridLines, xLabels };
  });

  constructor() {
    effect(() => {
      const preset = this.preset();
      const offset = this.offset();
      this.loadData(preset, offset);
    });
  }

  setPreset(p: TimePreset): void {
    this.preset.set(p);
    this.offset.set(0);
    this.expandedTeamId.set(null);
  }

  navPrev(): void {
    this.offset.update(o => o + 1);
    this.expandedTeamId.set(null);
  }

  navNext(): void {
    if (this.offset() === 0) return;
    this.offset.update(o => o - 1);
    this.expandedTeamId.set(null);
  }

  toggleTeam(teamId: number): void {
    if (this.expandedTeamId() === teamId) {
      this.expandedTeamId.set(null);
      return;
    }
    this.expandedTeamId.set(teamId);
    if (!this.keysByTeamId()[teamId]) this.loadKeys(teamId);
  }

  keysForTeam(teamId: number): KeyRow[] {
    return this.keysByTeamId()[teamId] ?? [];
  }

  showTooltip(rect: SvgRect, event: MouseEvent): void {
    const svgEl  = (event.currentTarget as SVGElement).closest('svg') as SVGSVGElement;
    const wrapEl = svgEl?.parentElement;
    if (!wrapEl) return;
    const wrapRect = wrapEl.getBoundingClientRect();
    this.tooltipState.set({
      teamName:  rect.teamName,
      cost:      rect.cost,
      timeLabel: rect.timeLabel,
      x: event.clientX - wrapRect.left,
      y: event.clientY - wrapRect.top - 56,
    });
  }

  hideTooltip(): void {
    this.tooltipState.set(null);
  }

  formatDollars(microCents: number): string {
    const d = microCents / MICRO_CENTS_PER_DOLLAR;
    return new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' }).format(d);
  }

  roundedTopPath(r: SvgRect): string {
    const rad = Math.min(3, r.width / 2);
    return `M${r.x},${r.y + rad} Q${r.x},${r.y} ${r.x + rad},${r.y} L${r.x + r.width - rad},${r.y} Q${r.x + r.width},${r.y} ${r.x + r.width},${r.y + rad} L${r.x + r.width},${r.y + r.height} L${r.x},${r.y + r.height} Z`;
  }

  private loadData(preset: TimePreset, offset: number): void {
    const { currStart, currEnd, prevStart, prevEnd } = calendarRange(preset, offset);
    const toIso = (d: Date) => d.toISOString();

    this.loading.set(true);
    this.error.set(false);
    this.currentBuckets.set([]);
    this.previousBuckets.set([]);
    this.tooltipState.set(null);

    forkJoin({
      current:  this.billingService.getTeamBudgetHistory(toIso(currStart), toIso(currEnd)),
      previous: this.billingService.getTeamBudgetHistory(toIso(prevStart), toIso(prevEnd)),
    }).subscribe({
      next: ({ current, previous }) => {
        this.currentBuckets.set(current.buckets);
        this.previousBuckets.set(previous.buckets);
        this.loading.set(false);
      },
      error: () => {
        this.error.set(true);
        this.loading.set(false);
      },
    });
  }

  private loadKeys(teamId: number): void {
    const { currStart, currEnd } = this.ranges();
    const toIso = (d: Date) => d.toISOString();

    this.keysLoadingTeamId.set(teamId);
    this.keysErrorTeamId.set(null);

    this.billingService.getKeyBudgetHistory(teamId, toIso(currStart), toIso(currEnd)).subscribe({
      next: res => {
        const keyMap = new Map<number, { name: string; cost: number }>();
        for (const b of res.buckets) {
          const ex = keyMap.get(b.api_key_id);
          if (ex) ex.cost += b.cost_micro_cents;
          else keyMap.set(b.api_key_id, { name: b.api_key_name, cost: b.cost_micro_cents });
        }
        const teamTotal = [...keyMap.values()].reduce((s, k) => s + k.cost, 0);
        const rows: KeyRow[] = [...keyMap.entries()]
          .sort(([, a], [, b]) => b.cost - a.cost)
          .map(([id, { name, cost }]) => ({
            id, name, cost,
            pct: teamTotal > 0 ? (cost / teamTotal) * 100 : 0,
          }));
        this.keysByTeamId.update(m => ({ ...m, [teamId]: rows }));
        this.keysLoadingTeamId.set(null);
      },
      error: () => {
        this.keysErrorTeamId.set(teamId);
        this.keysLoadingTeamId.set(null);
      },
    });
  }
}
