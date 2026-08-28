import { daysSince, formatLastUsed } from './date';

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
