export type TimePreset = 'day' | 'week' | 'month' | '6m' | 'year';

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
  { value: '6m', label: '6 Months' },
  { value: 'year', label: 'Year' },
];

export const VS_LABEL: Record<TimePreset, string> = {
  day: 'vs Yesterday',
  week: 'vs Prev Week',
  month: 'vs Last Month',
  '6m': 'vs Prev 6 Months',
  year: 'vs Last Year',
};

export const AVG_UNIT: Record<TimePreset, string> = {
  day: 'avg / hour',
  week: 'avg / day',
  month: 'avg / day',
  '6m': 'avg / month',
  year: 'avg / month',
};

export function calendarRange(preset: TimePreset, offset: number): CalendarRange {
  const now = new Date();
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
    case '6m': {
      const s = currStart.toLocaleDateString('en-US', { month: 'short', year: 'numeric' });
      const e = new Date(currEnd.getTime() - 86_400_000).toLocaleDateString('en-US', { month: 'short', year: 'numeric' });
      return `${s} - ${e}`;
    }
    case 'year':
      return String(currStart.getFullYear());
  }
}
