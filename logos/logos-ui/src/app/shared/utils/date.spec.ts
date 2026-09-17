import { daysSince, formatIsoDate, formatLastUsed } from './date';

describe('date utils', () => {
  const now = new Date('2026-08-26T12:00:00');

  describe('formatLastUsed', () => {
    it('renders "Never" for a missing timestamp', () => {
      expect(formatLastUsed(null, now)).toBe('Never');
      expect(formatLastUsed(undefined, now)).toBe('Never');
    });

    it('renders "Today" for a timestamp less than a day ago', () => {
      expect(formatLastUsed('2026-08-26T09:00:00', now)).toBe('Today');
    });

    it('renders the German date with the age in brackets', () => {
      expect(formatLastUsed('2026-08-25T12:00:00', now)).toBe('25.08.2026 (1 day ago)');
      expect(formatLastUsed('2026-08-24T09:00:00', now)).toBe('24.08.2026 (2 days ago)');
      expect(formatLastUsed('1996-06-02T00:00:00', now)).toBe('02.06.1996 (11042 days ago)');
    });
  });

  describe('formatIsoDate', () => {
    it('keeps the calendar date of a UTC midnight timestamp in every time zone', () => {
      // Catalogue valid_from values: the date part is the effective date and
      // must not shift by a day in UTC-negative time zones.
      expect(formatIsoDate('2025-08-01T00:00:00Z')).toBe('01.08.2025');
    });

    it('returns an em dash for missing or invalid values', () => {
      expect(formatIsoDate(null)).toBe('—');
      expect(formatIsoDate(undefined)).toBe('—');
      expect(formatIsoDate('not a date')).toBe('—');
    });
  });

  describe('daysSince', () => {
    it('counts whole days between the timestamp and now', () => {
      expect(daysSince('2026-08-26T12:00:00', now)).toBe(0);
      expect(daysSince('2026-08-25T11:59:59', now)).toBe(1);
      expect(daysSince('2026-07-27T12:00:00', now)).toBe(30);
    });

    it('clamps future timestamps to 0', () => {
      expect(daysSince('2026-08-27T12:00:00', now)).toBe(0);
    });
  });
});
