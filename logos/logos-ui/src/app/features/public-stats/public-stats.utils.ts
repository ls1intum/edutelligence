import { PublicStats, PublicStatsDays, PublicTeamStats } from './public-stats.service';

/** One row of a public-stats chart, as the page holds it. */
export interface ChartSlice {
  key: string;
  label: string;
  value: number;
  /** A CSS custom property (e.g. `var(--series-1)`), resolved per theme by the page styles. */
  color: string;
  /** True once the reader has ticked the slice out of the chart. */
  hidden: boolean;
  /** Short plain explanation shown under the label (key-type chart). */
  caption?: string;
}

/** A chart slice with its drawn geometry. */
export interface PieGeometry {
  slice: ChartSlice;
  path: string;
  /** Share of the visible total, rounded to whole percent. */
  percent: number;
}

/**
 * How many teams get a hue of their own. Categorical hues are assigned in
 * fixed order and never cycled, so the first team past this cap — like every
 * team after it — folds into the neutral "Other" slice instead.
 */
export const MAX_NAMED_TEAM_SLICES = 8;

export const OTHER_SLICE_COLOR = 'var(--series-other)';

/**
 * The wedge of a pie from startAngle to endAngle (radians, 0 = top,
 * clockwise). A single full turn is clamped just short of 2π — a 360° arc
 * has no distinct endpoints and collapses to nothing.
 */
export function pieSlicePath(cx: number, cy: number, r: number, startAngle: number, endAngle: number): string {
  const safeEnd = Math.min(endAngle, startAngle + 2 * Math.PI - 0.0001);
  const a1 = startAngle - Math.PI / 2;
  const a2 = safeEnd - Math.PI / 2;
  const largeArc = safeEnd - startAngle > Math.PI ? 1 : 0;
  const x1 = cx + r * Math.cos(a1);
  const y1 = cy + r * Math.sin(a1);
  const x2 = cx + r * Math.cos(a2);
  const y2 = cy + r * Math.sin(a2);
  return `M ${cx} ${cy} L ${x1} ${y1} A ${r} ${r} 0 ${largeArc} 1 ${x2} ${y2} Z`;
}

/**
 * Geometry for the slices that are actually on screen: hidden and zero-value
 * slices are dropped, and percentages are shares of what remains — hiding a
 * team re-partitions the pie, it does not punch a hole in it.
 */
export function buildPieGeometry(slices: ChartSlice[], cx = 100, cy = 100, r = 92): PieGeometry[] {
  const visible = slices.filter((s) => !s.hidden && s.value > 0);
  const total = visible.reduce((sum, s) => sum + s.value, 0);
  if (total === 0) return [];

  let angle = 0;
  return visible.map((slice) => {
    const fraction = slice.value / total;
    const start = angle;
    const end = angle + fraction * 2 * Math.PI;
    angle = end;
    return {
      slice,
      path: pieSlicePath(cx, cy, r, start, end),
      percent: Math.round(fraction * 100),
    };
  });
}

function teamLabel(team: PublicTeamStats): string {
  return team.team_name && team.team_name.length > 0 ? team.team_name : 'No team';
}

function teamKey(team: PublicTeamStats): string {
  return team.team_id == null ? 'none' : String(team.team_id);
}

/**
 * The teams' slices, in display order: most successful requests first, then
 * name. Colors come off this one ordering — the 1st team is always slot 1 —
 * and stay put afterwards, so hiding a team never repaints the rest. Teams
 * past the cap fold into "Other teams", which carries no hue of its own.
 */
export function teamSlices(teams: PublicTeamStats[]): ChartSlice[] {
  const sorted = [...teams]
    .filter((t) => t.requests > 0)
    .sort((a, b) => b.requests - a.requests || teamLabel(a).localeCompare(teamLabel(b)));

  const slices: ChartSlice[] = sorted.slice(0, MAX_NAMED_TEAM_SLICES).map((team, index) => ({
    key: teamKey(team),
    label: teamLabel(team),
    value: team.requests,
    color: `var(--series-${index + 1})`,
    hidden: false,
  }));

  const overflow = sorted.slice(MAX_NAMED_TEAM_SLICES);
  if (overflow.length > 0) {
    slices.push({
      key: 'other',
      label: 'Other teams',
      value: overflow.reduce((sum, t) => sum + t.requests, 0),
      color: OTHER_SLICE_COLOR,
      hidden: false,
    });
  }
  return slices;
}

/**
 * Human label for the selected rolling window, used under every number.
 * {@code all} reads as "all time"; otherwise "last N days".
 */
export function windowLabel(days: PublicStatsDays | string): string {
  if (days === 'all') return 'all time';
  return `last ${days} days`;
}

/** Successful requests by key type as segments: members' personal keys first. */
export function keyTypeSlices(stats: PublicStats): ChartSlice[] {
  const kt = stats.requests_by_key_type;
  const slices: ChartSlice[] = [
    {
      key: 'developer',
      label: 'Member keys',
      caption: 'Personal keys that belong to a team member.',
      value: kt.developer ?? 0,
      color: 'var(--series-1)',
      hidden: false,
    },
    {
      key: 'application',
      label: 'Application keys',
      caption: 'Keys for a team app. Each key has an environment tag.',
      value: kt.application ?? 0,
      color: 'var(--series-2)',
      hidden: false,
    },
    {
      // Kept as "Service keys" to match the stored key_type; the caption
      // answers what that type is for (automated jobs, not a person or app env).
      key: 'service',
      label: 'Service keys',
      caption: 'Keys for automated backend jobs. Not tied to a person or an app environment.',
      value: kt.service ?? 0,
      color: 'var(--series-3)',
      hidden: false,
    },
  ];
  // Only show the unknown row when deleted keys actually contribute — a zero
  // unknown would pad every empty chart with a meaningless legend entry.
  if ((kt.unknown ?? 0) > 0) {
    slices.push({
      key: 'unknown',
      label: 'Unknown key',
      caption: 'Requests whose API key was later deleted.',
      value: kt.unknown!,
      color: OTHER_SLICE_COLOR,
      hidden: false,
    });
  }
  return slices;
}

/** Local vs. cloud as segments: the self-hosted lane first. */
export function laneSlices(stats: PublicStats): ChartSlice[] {
  const lc = stats.local_cloud_requests;
  const slices: ChartSlice[] = [
    { key: 'local', label: 'Local', value: lc.local ?? 0, color: 'var(--series-1)', hidden: false },
    { key: 'cloud', label: 'Cloud', value: lc.cloud ?? 0, color: 'var(--series-2)', hidden: false },
  ];
  if ((lc.unknown ?? 0) > 0) {
    slices.push({
      key: 'unknown',
      label: 'Unknown lane',
      value: lc.unknown!,
      color: OTHER_SLICE_COLOR,
      hidden: false,
    });
  }
  return slices;
}

export function formatCount(value: number): string {
  return new Intl.NumberFormat().format(value);
}

export function formatAverage(value: number): string {
  return value.toLocaleString(undefined, { maximumFractionDigits: 2 });
}
