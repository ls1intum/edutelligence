import {
  Component,
  computed,
  effect,
  inject,
  signal,
  viewChild,
  ElementRef,
  ChangeDetectionStrategy,
} from '@angular/core';
import { BillingService, BudgetBucket } from '../../core/services/billing.service';
import { ErrorMessageComponent } from '../../shared/components/error-message/error-message';
import { DataTableComponent } from '../../shared/components/data-table/data-table';
import {
  TimePreset,
  calendarRange,
  periodLabel as periodLabelFn,
  PRESETS,
  VS_LABEL,
  AVG_UNIT,
} from '../../shared/utils/time-range';
import { TimeRangeBarComponent } from '../../shared/components/time-range-bar/time-range-bar';

const MICRO_CENTS_PER_DOLLAR = 100_000_000;

// Plotly palette + colour assignment ported from the React budget-history-chart:
// each team is hashed by name onto a fixed 8-colour palette so a given team keeps
// the same colour regardless of sort order.
const PALETTE = [
  '#F29C6E',
  '#3BE9DE',
  '#9D4EDD',
  '#06FFA5',
  '#EC4899',
  '#6366F1',
  '#F59E0B',
  '#14B8A6',
] as const;

function paletteColorForName(name: string): string {
  let sum = 0;
  for (const char of name) sum += char.charCodeAt(0);
  return PALETTE[sum % PALETTE.length];
}

export interface TeamRow {
  id: number;
  name: string;
  color: string;
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
  color: string;
  isTop: boolean;
}

// One time-bucket's worth of data, used by the crosshair tooltip to list every
// team at the hovered x position (mirrors the statistics unified tooltip).
interface BucketCol {
  centerX: number;
  label: string;
  rows: Array<{ teamName: string; color: string; cost: number }>;
  total: number;
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

// X-axis tick formats ported from Plotly's xAxisFormat:
//   day → %H:%M (24h), year → %b %Y, everything else → %b %d.
function formatBucketLabel(iso: string, preset: TimePreset): string {
  const d = new Date(iso);
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
  if (d >= 1) return `$${d.toFixed(0)}`;
  return `$${d.toFixed(2)}`;
}

@Component({
  selector: 'app-billing',
  standalone: true,
  imports: [ErrorMessageComponent, TimeRangeBarComponent, DataTableComponent],
  templateUrl: './billing.html',
  changeDetection: ChangeDetectionStrategy.Eager,
  styleUrl: './billing.scss',
})
export class Billing {
  private billingService = inject(BillingService);

  preset = signal<TimePreset>('month');
  offset = signal(0);

  readonly presets = PRESETS;

  loading = signal(true);
  error = signal(false);

  currentBuckets = signal<BudgetBucket[]>([]);
  previousBuckets = signal<BudgetBucket[]>([]);

  // Teams toggled via the chart legend. Empty set = all teams shown.
  selectedTeamIds = signal<Set<number>>(new Set());

  expandedTeamId = signal<number | null>(null);
  keysByTeamId = signal<Record<number, KeyRow[]>>({});
  keysLoadingTeamId = signal<number | null>(null);
  keysErrorTeamId = signal<number | null>(null);

  // Crosshair: which time-bucket the cursor is over, plus the clamped viewport
  // position for the (page-root, position:fixed) tooltip.
  hoverBucket = signal<number | null>(null);
  tooltipPos = signal<{ left: number; top: number } | null>(null);

  private readonly tooltipEl = viewChild<ElementRef<HTMLDivElement>>('tooltipEl');

  readonly CHART_W = 1000;
  readonly CHART_H = 150;
  readonly CHART_PAD_LEFT = 44;
  readonly CHART_PAD_BOTTOM = 20;
  readonly CHART_PAD_TOP = 6;
  readonly CHART_PAD_RIGHT = 8;

  private ranges = computed(() => calendarRange(this.preset(), this.offset()));

  periodLabel = computed(() => periodLabelFn(this.preset(), this.offset(), this.ranges()));

  vsLabel = computed(() => VS_LABEL[this.preset()]);

  breakdownColumns = computed(() => ['', 'TEAM', 'SPEND', '% OF TOTAL', this.vsLabel().toUpperCase()]);

  currentTotal = computed(() => this.currentBuckets().reduce((s, b) => s + b.cost_micro_cents, 0));

  previousTotal = computed(() =>
    this.previousBuckets().reduce((s, b) => s + b.cost_micro_cents, 0),
  );

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
    const curr = this.currentBuckets();
    const prev = this.previousBuckets();
    const total = this.currentTotal();

    const teamMap = new Map<number, { name: string; cost: number }>();
    for (const b of curr) {
      const ex = teamMap.get(b.team_id);
      if (ex) ex.cost += b.cost_micro_cents;
      else teamMap.set(b.team_id, { name: b.team_name, cost: b.cost_micro_cents });
    }

    const prevMap = new Map<number, number>();
    for (const b of prev)
      prevMap.set(b.team_id, (prevMap.get(b.team_id) ?? 0) + b.cost_micro_cents);

    return [...teamMap.entries()]
      // Only teams that actually spent in this period — keeps the legend, the
      // breakdown table, and (since the legend is additive-selection) the chart
      // from ever surfacing a zero-spend team.
      .filter(([, { cost }]) => cost > 0)
      .sort(([, a], [, b]) => b.cost - a.cost)
      .map(([id, { name, cost }]) => {
        const prevCost = prevMap.get(id) ?? 0;
        return {
          id,
          name,
          color: paletteColorForName(name),
          cost,
          prevCost,
          pct: total > 0 ? (cost / total) * 100 : 0,
          trendPct: prevCost > 0 ? ((cost - prevCost) / prevCost) * 100 : null,
        };
      });
  });

  chartData = computed((): ChartOutput => {
    const buckets = this.currentBuckets();
    const sel = this.selectedTeamIds();
    // Legend filter (Plotly-style): empty selection => show every team.
    const teams =
      sel.size === 0 ? this.teams() : this.teams().filter((t) => sel.has(t.id));
    const preset = this.preset();

    if (buckets.length === 0 || teams.length === 0) {
      return { rects: [], gridLines: [], xLabels: [], buckets: [], plotTop: 0, plotBottom: 0, barW: 0 };
    }

    const bucketTimes = [...new Set(buckets.map((b) => b.bucket_ts))].sort();
    const n = bucketTimes.length;

    const bars = bucketTimes.map((ts) => {
      const slice = buckets.filter((b) => b.bucket_ts === ts);
      let total = 0;
      const stacks = teams
        .map((t) => {
          const v = slice.find((b) => b.team_id === t.id)?.cost_micro_cents ?? 0;
          total += v;
          return { color: t.color, teamName: t.name, value: v };
        })
        .filter((s) => s.value > 0);
      return { ts, label: formatBucketLabel(ts, preset), stacks, total };
    });

    const rawMax = Math.max(...bars.map((b) => b.total));
    const maxVal = niceMax(rawMax);

    const plotW = this.CHART_W - this.CHART_PAD_LEFT - this.CHART_PAD_RIGHT;
    const plotH = this.CHART_H - this.CHART_PAD_TOP - this.CHART_PAD_BOTTOM;
    const slotW = plotW / n;
    const barW = Math.max(5, Math.min(24, slotW * 0.65));
    const barBase = this.CHART_PAD_TOP + plotH;

    const rects: SvgRect[] = [];
    const bucketCols: BucketCol[] = [];
    for (let i = 0; i < bars.length; i++) {
      const bar = bars[i];
      const centerX = this.CHART_PAD_LEFT + i * slotW + slotW / 2;
      const barX = centerX - barW / 2;
      let cumY = barBase;

      const barRects: SvgRect[] = [];
      for (const seg of bar.stacks) {
        const h = (seg.value / maxVal) * plotH;
        if (h < 0.5) continue;
        cumY -= h;
        barRects.push({
          x: barX,
          y: cumY,
          width: barW,
          height: h,
          color: seg.color,
          isTop: false,
        });
      }
      if (barRects.length > 0) barRects[barRects.length - 1].isTop = true;
      rects.push(...barRects);

      bucketCols.push({
        centerX,
        label: bar.label,
        total: bar.total,
        rows: bar.stacks
          .map((s) => ({ teamName: s.teamName, color: s.color, cost: s.value }))
          .sort((a, b) => b.cost - a.cost),
      });
    }

    const gridLines = [0.25, 0.5, 0.75, 1.0].map((f) => ({
      y: this.CHART_PAD_TOP + plotH * (1 - f),
      label: formatCostShort(f * maxVal),
    }));

    const every = Math.max(1, Math.ceil(n / 8));
    const xLabels = bars
      .filter((_, i) => i % every === 0)
      .map((b, fi) => ({
        x: this.CHART_PAD_LEFT + fi * every * slotW + slotW / 2,
        label: b.label,
      }));

    return {
      rects,
      gridLines,
      xLabels,
      buckets: bucketCols,
      plotTop: this.CHART_PAD_TOP,
      plotBottom: barBase,
      barW,
    };
  });

  // Crosshair tooltip model for the hovered time-bucket (all teams + total).
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
      this.loadData(preset, offset);
    });

    effect(() => {
      this.preset();
      this.offset();
      this.expandedTeamId.set(null);
      this.selectedTeamIds.set(new Set());
      this.hoverBucket.set(null);
      this.tooltipPos.set(null);
    });
  }

  toggleLegendTeam(teamId: number): void {
    this.selectedTeamIds.update((prev) => {
      const next = new Set(prev);
      if (next.has(teamId)) next.delete(teamId);
      else next.add(teamId);
      return next;
    });
  }

  isTeamVisible(teamId: number): boolean {
    const sel = this.selectedTeamIds();
    return sel.size === 0 || sel.has(teamId);
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

  // Crosshair follows the cursor across the plot and snaps to the nearest
  // time-bucket; the tooltip (page-root, position:fixed) then lists every team
  // at that bucket. Mirrors the statistics chart's unified hover.
  onPlotMove(event: MouseEvent): void {
    const cd = this.chartData();
    const cols = cd.buckets;
    if (cols.length === 0) {
      this.onPlotLeave();
      return;
    }
    const svg = (event.currentTarget as Element).closest('svg') as SVGSVGElement | null;
    if (!svg) return;
    const rect = svg.getBoundingClientRect();
    if (rect.width === 0) return;

    // Pointer x in viewBox units.
    const vbX = (event.clientX - rect.left) * (this.CHART_W / rect.width);

    // Snap to the nearest bar by its centre, but only engage when the cursor is
    // actually near that bar — otherwise the crosshair would appear in the empty
    // gaps between bars.
    let nearest = 0;
    let bestDist = Infinity;
    for (let i = 0; i < cols.length; i++) {
      const d = Math.abs(vbX - cols[i].centerX);
      if (d < bestDist) {
        bestDist = d;
        nearest = i;
      }
    }
    const hitRadius = cd.barW / 2 + 6;
    if (bestDist > hitRadius) {
      this.onPlotLeave();
      return;
    }

    this.hoverBucket.set(nearest);
    this.tooltipPos.set(this.clampTooltip(event.clientX, event.clientY));
  }

  onPlotLeave(): void {
    this.hoverBucket.set(null);
    this.tooltipPos.set(null);
  }

  // Keep the tooltip inside the viewport: prefer the cursor's right side, flip to
  // the left when it would overflow, and clamp top/bottom. Uses the rendered
  // tooltip size (stable while hovering one bucket; falls back to an estimate on
  // the very first frame).
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

  formatDollars(microCents: number): string {
    const d = microCents / MICRO_CENTS_PER_DOLLAR;
    return new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' }).format(d);
  }

  // Hover precision matches Plotly's `%{y:.6f}` tooltip in the React chart.
  formatDollars6(microCents: number): string {
    const d = microCents / MICRO_CENTS_PER_DOLLAR;
    return `$${d.toFixed(6)}`;
  }

  roundedTopPath(r: SvgRect): string {
    const rad = Math.min(3, r.width / 2);
    return `M${r.x},${r.y + rad} Q${r.x},${r.y} ${r.x + rad},${r.y} L${r.x + r.width - rad},${r.y} Q${r.x + r.width},${r.y} ${r.x + r.width},${r.y + rad} L${r.x + r.width},${r.y + r.height} L${r.x},${r.y + r.height} Z`;
  }

  private async loadData(preset: TimePreset, offset: number): Promise<void> {
    const { currStart, currEnd, prevStart, prevEnd } = calendarRange(preset, offset);
    const toIso = (d: Date) => d.toISOString();

    this.loading.set(true);
    this.error.set(false);
    this.currentBuckets.set([]);
    this.previousBuckets.set([]);
    this.hoverBucket.set(null);
    this.tooltipPos.set(null);

    try {
      const [current, previous] = await Promise.all([
        this.billingService.getTeamBudgetHistory(toIso(currStart), toIso(currEnd)),
        this.billingService.getTeamBudgetHistory(toIso(prevStart), toIso(prevEnd)),
      ]);
      this.currentBuckets.set(current.buckets);
      this.previousBuckets.set(previous.buckets);
    } catch {
      this.error.set(true);
    } finally {
      this.loading.set(false);
    }
  }

  private async loadKeys(teamId: number): Promise<void> {
    const { currStart, currEnd } = this.ranges();
    const toIso = (d: Date) => d.toISOString();

    this.keysLoadingTeamId.set(teamId);
    this.keysErrorTeamId.set(null);

    try {
      const res = await this.billingService.getKeyBudgetHistory(teamId, toIso(currStart), toIso(currEnd));
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
          id,
          name,
          cost,
          pct: teamTotal > 0 ? (cost / teamTotal) * 100 : 0,
        }));
      this.keysByTeamId.update((m) => ({ ...m, [teamId]: rows }));
    } catch {
      this.keysErrorTeamId.set(teamId);
    } finally {
      this.keysLoadingTeamId.set(null);
    }
  }
}
