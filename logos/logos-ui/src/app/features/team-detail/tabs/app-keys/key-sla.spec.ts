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
  it('offers exactly three tiers, with medium as the default', () => {
    expect(SLA_OPTIONS.map((o) => o.value)).toEqual(['high', 'medium', 'low']);
    expect(DEFAULT_SLA).toBe('medium');
  });

  it('maps each tier to the priority the queue buckets it as', () => {
    expect(slaOfPriority(SLA_PRIORITY.high)).toBe('high');
    expect(slaOfPriority(SLA_PRIORITY.medium)).toBe('medium');
    expect(slaOfPriority(SLA_PRIORITY.low)).toBe('low');
  });

  it('reads a key with no priority chosen yet as the default tier', () => {
    expect(slaOfPriority(0)).toBe(DEFAULT_SLA);
    expect(slaOfPriority(null)).toBe(DEFAULT_SLA);
    expect(slaOfPriority(undefined)).toBe(DEFAULT_SLA);
  });

  it('reads a non-canonical priority as medium, matching the NORMAL bucket', () => {
    // 2..9 except 5 all fall back to NORMAL in Priority.from_int.
    for (const raw of [2, 3, 4, 6, 7, 8, 9]) {
      expect(slaOfPriority(raw)).toBe('medium');
    }
  });

  it('ranks the strictest tier first', () => {
    expect(slaRank('high')).toBeLessThan(slaRank('medium'));
    expect(slaRank('medium')).toBeLessThan(slaRank('low'));
  });
});
