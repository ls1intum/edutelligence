export type TimePreset = 'day' | 'week' | 'month' | '30d' | '6m' | 'year';

export interface CalendarRange {
  currStart: Date;
  currEnd: Date;
  prevStart: Date;
  prevEnd: Date;
}

export const PRESETS: ReadonlyArray<{ value: TimePreset; label: string }> = [
  { value: 'day', label: 'Day' },
  { value: 'week', label: 'Week' },
  { value: 'month', label: 'Month' },
  { value: '30d', label: 'Last 30 Days' },
  { value: '6m', label: '6 Months' },
  { value: 'year', label: 'Year' },
];

export const VS_LABEL: Record<TimePreset, string> = {
  day: 'vs Yesterday',
  week: 'vs Prev Week',
  month: 'vs Last Month',
  '30d': 'vs Prev 30 Days',
  '6m': 'vs Prev 6 Months',
  year: 'vs Last Year',
};

export const AVG_UNIT: Record<TimePreset, string> = {
  day: 'avg / hour',
  week: 'avg / day',
  month: 'avg / day',
  '30d': 'avg / day',
  '6m': 'avg / month',
  year: 'avg / month',
};

export function calendarRange(
  preset: TimePreset,
  offset: number,
  now: Date = new Date(),
): CalendarRange {
  let currStart: Date, currEnd: Date, prevStart: Date, prevEnd: Date;

  switch (preset) {
    case 'day': {
      currStart = new Date(now.getFullYear(), now.getMonth(), now.getDate() - offset);
      currEnd = new Date(currStart.getFullYear(), currStart.getMonth(), currStart.getDate() + 1);
      prevStart = new Date(currStart.getFullYear(), currStart.getMonth(), currStart.getDate() - 1);
      prevEnd = currStart;
      break;
    }
    case 'week': {
      const dow = now.getDay() === 0 ? 7 : now.getDay();
      const thisMonday = new Date(now.getFullYear(), now.getMonth(), now.getDate() - dow + 1);
      currStart = new Date(thisMonday.getFullYear(), thisMonday.getMonth(), thisMonday.getDate() - offset * 7);
      currEnd = new Date(currStart.getFullYear(), currStart.getMonth(), currStart.getDate() + 7);
      prevStart = new Date(currStart.getFullYear(), currStart.getMonth(), currStart.getDate() - 7);
      prevEnd = currStart;
      break;
    }
    case 'month': {
      currStart = new Date(now.getFullYear(), now.getMonth() - offset, 1);
      currEnd = new Date(currStart.getFullYear(), currStart.getMonth() + 1, 1);
      prevStart = new Date(currStart.getFullYear(), currStart.getMonth() - 1, 1);
      prevEnd = currStart;
      break;
    }
    case '30d': {
      // Rolling window ending "now" (not calendar-aligned): offset 0 is the
      // last 30 days, offset 1 the 30 days before that, and so on.
      currEnd = new Date(now.getTime() - offset * 30 * 86_400_000);
      currStart = new Date(currEnd.getTime() - 30 * 86_400_000);
      prevStart = new Date(currStart.getTime() - 30 * 86_400_000);
      prevEnd = currStart;
      break;
    }
    case '6m': {
      const endMonth = new Date(now.getFullYear(), now.getMonth() + 1 - offset * 6, 1);
      currStart = new Date(endMonth.getFullYear(), endMonth.getMonth() - 6, 1);
      currEnd = endMonth;
      prevStart = new Date(currStart.getFullYear(), currStart.getMonth() - 6, 1);
      prevEnd = currStart;
      break;
    }
    case 'year': {
      const year = now.getFullYear() - offset;
      currStart = new Date(year, 0, 1);
      currEnd = new Date(year + 1, 0, 1);
      prevStart = new Date(year - 1, 0, 1);
      prevEnd = currStart;
      break;
    }
  }

  return { currStart: currStart!, currEnd: currEnd!, prevStart: prevStart!, prevEnd: prevEnd! };
}

/**
 * The start of the period a preset+offset denotes at `nowMs` — the instant
 * that pins the period (local midnight for a day, the Monday for a week, the
 * first of the month for a month, January 1 for a year).
 *
 * Two instants denote the same period iff they agree here, so the start
 * doubles as the period's identity. That is what makes the rollover test
 * below a single comparison instead of a switch over the presets.
 */
export function periodStartMs(preset: TimePreset, offset: number, nowMs: number): number {
  return calendarRange(preset, offset, new Date(nowMs)).currStart.getTime();
}

/**
 * Whether the period a preset+offset denotes at `nowMs` is a different
 * calendar unit than the one it denoted at `anchorMs` — that is, whether the
 * calendar rolled over (midnight, a Monday, the first of a month, January 1)
 * while a range resolved from `anchorMs` was still on screen.
 *
 * `customRangeActive` short-circuits to false: a range the user picked by
 * hand is pinned exactly where they put it, and the calendar moving underneath
 * it is no reason to drag them out of the window they chose.
 *
 * The rolling preset (`30d`) is deliberately excluded: its range is anchored
 * to the instant it was picked, so `periodStartMs` moves with `nowMs` on
 * every comparison and would report a rollover on every tick. "Last 30 days"
 * names no calendar unit, so there is nothing for it to roll into — the
 * window keeps the start it was picked with and only grows its end.
 */
export function periodRolloverDue(
  preset: TimePreset,
  offset: number,
  anchorMs: number,
  nowMs: number,
  customRangeActive: boolean,
): boolean {
  if (customRangeActive) return false;
  if (preset === '30d') return false;
  return periodStartMs(preset, offset, anchorMs) !== periodStartMs(preset, offset, nowMs);
}

export function periodLabel(preset: TimePreset, offset: number, range: CalendarRange): string {
  const { currStart, currEnd } = range;
  switch (preset) {
    case 'day':
      if (offset === 0) return 'Today';
      if (offset === 1) return 'Yesterday';
      return currStart.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
    case 'week': {
      const end = new Date(currEnd.getTime() - 86_400_000);
      return `${currStart.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })} - ${end.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })}`;
    }
    case 'month':
      return currStart.toLocaleDateString('en-US', { month: 'long', year: 'numeric' });
    case '30d': {
      if (offset === 0) return 'Last 30 Days';
      const e = new Date(currEnd.getTime() - 1);
      return `${currStart.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })} - ${e.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })}`;
    }
    case '6m': {
      const s = currStart.toLocaleDateString('en-US', { month: 'short', year: 'numeric' });
      const e = new Date(currEnd.getTime() - 86_400_000).toLocaleDateString('en-US', { month: 'short', year: 'numeric' });
      return `${s} - ${e}`;
    }
    case 'year':
      return String(currStart.getFullYear());
  }
}
