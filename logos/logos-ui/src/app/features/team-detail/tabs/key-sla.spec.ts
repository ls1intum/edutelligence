import { DEFAULT_SLA, SLA_OPTIONS, SLA_PRIORITY, slaOfPriority, slaRank } from './key-sla';

/**
 * The SLA tiers shown per application key.
 *
 * A tier is only a reading of `api_keys.default_priority`, and the orchestrator
 * — not this file — decides what a stored number means: `Priority.from_int`
 * recognises exactly 1, 5 and 10 and buckets everything else as NORMAL. If the
 * mapping here drifted from that, an owner would be told their key is served at
 * a tier the queue never gives it, which is the one thing an SLA must not do.
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

  it('maps each tier to the priority the queue buckets it as', () => {
    expect(slaOfPriority(SLA_PRIORITY['ux-critical'])).toBe('ux-critical');
    expect(slaOfPriority(SLA_PRIORITY['ux-high-prio'])).toBe('ux-high-prio');
    expect(slaOfPriority(SLA_PRIORITY['ux-background'])).toBe('ux-background');
  });

  it('reads a key with no priority chosen yet as the default tier', () => {
    expect(slaOfPriority(0)).toBe(DEFAULT_SLA);
    expect(slaOfPriority(null)).toBe(DEFAULT_SLA);
    expect(slaOfPriority(undefined)).toBe(DEFAULT_SLA);
  });

  it('reads a non-canonical priority as the default tier, matching the NORMAL bucket', () => {
    // 2..9 except 5 all fall back to NORMAL in Priority.from_int.
    for (const raw of [2, 3, 4, 6, 7, 8, 9]) {
      expect(slaOfPriority(raw)).toBe(DEFAULT_SLA);
    }
  });

  it('ranks the strictest tier first', () => {
    expect(slaRank('ux-critical')).toBeLessThan(slaRank('ux-high-prio'));
    expect(slaRank('ux-high-prio')).toBeLessThan(slaRank('ux-background'));
  });
});
