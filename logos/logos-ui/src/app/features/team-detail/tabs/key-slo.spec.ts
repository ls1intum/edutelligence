import {
  DEFAULT_SLO,
  INHERITED_SLO_HINT,
  SLO_OPTIONS,
  SLO_PRIORITY,
  effectiveSlo,
  isUnsetPriority,
  sloOfPriority,
  sloRank,
} from './key-slo';

/**
 * The SLO tiers shown per application key.
 *
 * A tier is only a reading of `api_keys.default_priority`, and the orchestrator
 * — not this file — decides what a stored number means: `Priority.from_int`
 * recognises exactly 1, 5 and 10 and buckets everything else as NORMAL. An
 * unset key (0) inherits the team's priority, matching `resolve_queue_priority`.
 */
describe('key SLO tiers', () => {
  it('offers exactly three tiers, with ux-high-prio as the default', () => {
    expect(SLO_OPTIONS.map((o) => o.value)).toEqual([
      'ux-critical',
      'ux-high-prio',
      'ux-background',
    ]);
    expect(DEFAULT_SLO).toBe('ux-high-prio');
  });

  it('describes queue behaviour for ux-critical, not model warmth', () => {
    const critical = SLO_OPTIONS.find((o) => o.value === 'ux-critical');
    expect(critical?.hint.toLowerCase()).toContain('queue');
    expect(critical?.hint.toLowerCase()).not.toContain('warm');
    expect(INHERITED_SLO_HINT.toLowerCase()).toContain('team');
  });

  it('maps each tier to the priority the queue buckets it as', () => {
    expect(sloOfPriority(SLO_PRIORITY['ux-critical'])).toBe('ux-critical');
    expect(sloOfPriority(SLO_PRIORITY['ux-high-prio'])).toBe('ux-high-prio');
    expect(sloOfPriority(SLO_PRIORITY['ux-background'])).toBe('ux-background');
  });

  it('treats 0 / null / undefined as an unset (inherited) priority', () => {
    expect(isUnsetPriority(0)).toBe(true);
    expect(isUnsetPriority(null)).toBe(true);
    expect(isUnsetPriority(undefined)).toBe(true);
    expect(isUnsetPriority(5)).toBe(false);
  });

  it('reads an unset key as the team tier when the team has one', () => {
    expect(effectiveSlo(0, 10)).toBe('ux-critical');
    expect(effectiveSlo(0, 1)).toBe('ux-background');
    expect(effectiveSlo(null, 5)).toBe('ux-high-prio');
  });

  it('reads an unset key as the default tier when the team has none', () => {
    expect(effectiveSlo(0, 0)).toBe(DEFAULT_SLO);
    expect(effectiveSlo(0, null)).toBe(DEFAULT_SLO);
    expect(effectiveSlo(0, undefined)).toBe(DEFAULT_SLO);
  });

  it('reads a non-canonical priority as the default tier, matching the NORMAL bucket', () => {
    // 2..9 except 5 all fall back to NORMAL in Priority.from_int.
    for (const raw of [2, 3, 4, 6, 7, 8, 9]) {
      expect(sloOfPriority(raw)).toBe(DEFAULT_SLO);
      expect(effectiveSlo(raw)).toBe(DEFAULT_SLO);
    }
  });

  it('ranks the strictest tier first', () => {
    expect(sloRank('ux-critical')).toBeLessThan(sloRank('ux-high-prio'));
    expect(sloRank('ux-high-prio')).toBeLessThan(sloRank('ux-background'));
  });
});
