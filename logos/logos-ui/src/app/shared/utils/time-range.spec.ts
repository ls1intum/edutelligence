import { calendarRange, periodRolloverDue, periodStartMs } from './time-range';

// All instants are built from local time components, so the expectations hold
// in any timezone: the ranges under test are local-calendar ranges, and the
// comparisons below never span a named instant.

const eveningOf = (year: number, month: number, day: number) =>
  new Date(year, month, day, 23, 50).getTime();
const afterMidnightOf = (year: number, month: number, day: number) =>
  new Date(year, month, day, 0, 10).getTime();

describe('periodStartMs', () => {
  it('pins a day to its local midnight', () => {
    expect(periodStartMs('day', 0, eveningOf(2026, 8, 6))).toBe(
      new Date(2026, 8, 6, 0, 0, 0, 0).getTime(),
    );
    // The same midnight at any hour of the day, the anchor does not crawl
    // forward with the clock.
    expect(periodStartMs('day', 0, new Date(2026, 8, 6, 0, 30).getTime())).toBe(
      new Date(2026, 8, 6, 0, 0, 0, 0).getTime(),
    );
  });

  it('pins a week to its Monday', () => {
    const wednesday = new Date(2026, 5, 10, 12);
    const dow = wednesday.getDay() || 7;
    const monday = new Date(2026, 5, 10 - dow + 1, 0, 0, 0, 0);
    expect(periodStartMs('week', 0, wednesday.getTime())).toBe(monday.getTime());
  });

  it('pins a month to the first', () => {
    expect(periodStartMs('month', 0, new Date(2026, 8, 15, 10).getTime())).toBe(
      new Date(2026, 8, 1, 0, 0, 0, 0).getTime(),
    );
  });

  it('pins a year to January 1st', () => {
    expect(periodStartMs('year', 0, new Date(2026, 11, 31, 23, 0).getTime())).toBe(
      new Date(2026, 0, 1, 0, 0, 0, 0).getTime(),
    );
  });

  it('moves with the clock for the rolling 30-day window', () => {
    // The 30-day preset is anchored to the instant it was picked, so its start
    // is not a calendar boundary at all. That is exactly why the rollover
    // test below excludes it.
    const earlier = periodStartMs('30d', 0, eveningOf(2026, 8, 6));
    const later = periodStartMs('30d', 0, afterMidnightOf(2026, 8, 7));
    expect(later).not.toBe(earlier);
    // The start crawled exactly as far as the clock did: 23:50 to 00:10 is
    // twenty minutes, and the window follows.
    expect(later - earlier).toBe(20 * 60_000);
  });
});

describe('periodRolloverDue', () => {
  it('fires for a day once the midnight has passed', () => {
    const anchor = eveningOf(2026, 8, 6);
    expect(periodRolloverDue('day', 0, anchor, afterMidnightOf(2026, 8, 7), false)).toBe(true);
  });

  it('does not fire inside the same day', () => {
    const anchor = eveningOf(2026, 8, 6);
    expect(periodRolloverDue('day', 0, anchor, anchor + 30_000, false)).toBe(false);
    const earlyMorning = new Date(2026, 8, 6, 0, 5).getTime();
    const lateEvening = new Date(2026, 8, 6, 23, 59).getTime();
    expect(periodRolloverDue('day', 0, earlyMorning, lateEvening, false)).toBe(false);
  });

  it('fires for a picked past day when it stops being the day it was named after', () => {
    // "Yesterday" at 23:50 is a different day than "yesterday" at 00:10: the
    // name kept its meaning only by moving. The page has to notice, because
    // the range on screen still covers the old one.
    const anchor = eveningOf(2026, 8, 6);
    const afterMidnight = afterMidnightOf(2026, 8, 7);
    expect(periodRolloverDue('day', 1, anchor, afterMidnight, false)).toBe(true);
    // Within the same night the named day does not move yet.
    expect(periodRolloverDue('day', 1, anchor, anchor + 30_000, false)).toBe(false);
  });

  it('fires for a week only when the Monday rolls in', () => {
    const wednesday = new Date(2026, 5, 10, 12);
    const dow = wednesday.getDay() || 7;
    const monday = new Date(2026, 5, 10 - dow + 1, 0, 0, 0, 0);
    const nextMonday = new Date(
      monday.getFullYear(),
      monday.getMonth(),
      monday.getDate() + 7,
      0,
      30,
    );
    const anHourLater = wednesday.getTime() + 3600_000;
    expect(periodRolloverDue('week', 0, wednesday.getTime(), anHourLater, false)).toBe(false);
    expect(periodRolloverDue('week', 0, wednesday.getTime(), nextMonday.getTime(), false)).toBe(true);
  });

  it('fires for a month only on the first', () => {
    const midSeptember = new Date(2026, 8, 15, 10).getTime();
    const sameMonthLater = new Date(2026, 8, 15, 23, 59).getTime();
    const firstOfOctober = new Date(2026, 9, 1, 0, 5).getTime();
    expect(periodRolloverDue('month', 0, midSeptember, sameMonthLater, false)).toBe(false);
    expect(periodRolloverDue('month', 0, midSeptember, firstOfOctober, false)).toBe(true);
  });

  it('fires for the six-month window when its month boundary rolls', () => {
    const endOfSeptember = new Date(2026, 8, 30, 23, 50).getTime();
    const fiveMinutesLater = new Date(2026, 8, 30, 23, 55).getTime();
    const firstOfOctober = new Date(2026, 9, 1, 0, 5).getTime();
    expect(periodRolloverDue('6m', 0, endOfSeptember, fiveMinutesLater, false)).toBe(false);
    expect(periodRolloverDue('6m', 0, endOfSeptember, firstOfOctober, false)).toBe(true);
  });

  it('fires for a year only on January 1st', () => {
    const newYearsEve = new Date(2026, 11, 31, 23, 50).getTime();
    const fiveMinutesLater = new Date(2026, 11, 31, 23, 55).getTime();
    const newYear = new Date(2027, 0, 1, 0, 10).getTime();
    expect(periodRolloverDue('year', 0, newYearsEve, fiveMinutesLater, false)).toBe(false);
    expect(periodRolloverDue('year', 0, newYearsEve, newYear, false)).toBe(true);
  });

  it('never fires for the rolling 30-day window', () => {
    // Its start moves with every comparison, so it is excluded rather than
    // compared: re-anchoring it on each tick would change what the selection
    // means instead of noticing that the calendar moved.
    const evening = eveningOf(2026, 8, 6);
    const afterMidnight = afterMidnightOf(2026, 8, 7);
    expect(periodRolloverDue('30d', 0, evening, afterMidnight, false)).toBe(false);
    expect(periodRolloverDue('30d', 1, evening, afterMidnight, false)).toBe(false);
  });

  it('never fires while a custom range is on screen', () => {
    // A range the user picked by hand is pinned where they put it; the
    // calendar rolling under it is no reason to drag them out of it.
    const evening = eveningOf(2026, 8, 6);
    const afterMidnight = afterMidnightOf(2026, 8, 7);
    expect(periodRolloverDue('day', 0, evening, afterMidnight, true)).toBe(false);
    expect(periodRolloverDue('week', 0, evening, afterMidnight, true)).toBe(false);
  });
});

describe('calendarRange with an explicit instant', () => {
  it('resolves "today" from the given instant, not from the wall clock', () => {
    const lateEvening = new Date(2026, 8, 6, 23, 50);
    const range = calendarRange('day', 0, lateEvening);
    expect(range.currStart).toEqual(new Date(2026, 8, 6, 0, 0, 0, 0));
    expect(range.currEnd).toEqual(new Date(2026, 8, 7, 0, 0, 0, 0));
  });

  it('still defaults to the wall clock when no instant is given', () => {
    const now = new Date();
    const range = calendarRange('day', 0);
    expect(range.currStart).toEqual(
      new Date(now.getFullYear(), now.getMonth(), now.getDate(), 0, 0, 0, 0),
    );
  });
});
