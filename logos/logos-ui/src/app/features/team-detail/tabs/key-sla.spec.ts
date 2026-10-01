import {
  DEFAULT_SLA,
  INHERITED_SLA_HINT,
  SLA_OPTIONS,
  SLA_PRIORITY,
  effectiveSla,
  isUnsetPriority,
  slaOfPriority,
  slaRank,
} from './key-sla';

/**
 * The SLA tiers shown per application key.
 *
 * A tier is only a reading of `api_keys.default_priority`, and the orchestrator
 * — not this file — decides what a stored number means: `Priority.from_int`
 * recognises exactly 1, 5 and 10 and buckets everything else as NORMAL. An
 * unset key (0) inherits the team's priority, matching `resolve_queue_priority`.
 */
describe('key SLA tiers', () => {
  it('offers exactly three tiers, with ux-high-prio as the default', () => {
    expect(SLA_OPTIONS.map((o) => o.value)).toEqual([
      'ux-critical',
      'ux-high-prio',
      'ux-background',
    ]);
    expect(DEFAULT_SLA).toBe('ux-high-prio');
  });

  it('describes queue behaviour for ux-critical, not model warmth', () => {
    const critical = SLA_OPTIONS.find((o) => o.value === 'ux-critical');
    expect(critical?.hint.toLowerCase()).toContain('queue');
    expect(critical?.hint.toLowerCase()).not.toContain('warm');
    expect(INHERITED_SLA_HINT.toLowerCase()).toContain('team');
  });

  it('maps each tier to the priority the queue buckets it as', () => {
    expect(slaOfPriority(SLA_PRIORITY['ux-critical'])).toBe('ux-critical');
    expect(slaOfPriority(SLA_PRIORITY['ux-high-prio'])).toBe('ux-high-prio');
    expect(slaOfPriority(SLA_PRIORITY['ux-background'])).toBe('ux-background');
  });

  it('treats 0 / null / undefined as an unset (inherited) priority', () => {
    expect(isUnsetPriority(0)).toBe(true);
    expect(isUnsetPriority(null)).toBe(true);
    expect(isUnsetPriority(undefined)).toBe(true);
    expect(isUnsetPriority(5)).toBe(false);
  });

  it('reads an unset key as the team tier when the team has one', () => {
    expect(effectiveSla(0, 10)).toBe('ux-critical');
    expect(effectiveSla(0, 1)).toBe('ux-background');
    expect(effectiveSla(null, 5)).toBe('ux-high-prio');
  });

  it('reads an unset key as the default tier when the team has none', () => {
    expect(effectiveSla(0, 0)).toBe(DEFAULT_SLA);
    expect(effectiveSla(0, null)).toBe(DEFAULT_SLA);
    expect(effectiveSla(0, undefined)).toBe(DEFAULT_SLA);
  });

  it('reads a non-canonical priority as the default tier, matching the NORMAL bucket', () => {
    // 2..9 except 5 all fall back to NORMAL in Priority.from_int.
    for (const raw of [2, 3, 4, 6, 7, 8, 9]) {
      expect(slaOfPriority(raw)).toBe(DEFAULT_SLA);
      expect(effectiveSla(raw)).toBe(DEFAULT_SLA);
    }
  });

  it('ranks the strictest tier first', () => {
    expect(slaRank('ux-critical')).toBeLessThan(slaRank('ux-high-prio'));
    expect(slaRank('ux-high-prio')).toBeLessThan(slaRank('ux-background'));
  });
});
