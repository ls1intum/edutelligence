import { SLA_PRIORITY, slaOfPriority, slaRank } from './key-sla';

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
  it('maps the canonical priorities to their tier', () => {
    expect(slaOfPriority(SLA_PRIORITY.high)).toBe('high');
    expect(slaOfPriority(SLA_PRIORITY.medium)).toBe('medium');
    expect(slaOfPriority(SLA_PRIORITY.low)).toBe('low');
  });

  it('treats an unset priority as inherited rather than as a tier', () => {
    expect(slaOfPriority(0)).toBe('inherit');
    expect(slaOfPriority(null)).toBe('inherit');
    expect(slaOfPriority(undefined)).toBe('inherit');
  });

  it('shows a non-canonical priority as medium, matching the NORMAL bucket', () => {
    // 2..9 except 5 all fall back to NORMAL in Priority.from_int.
    for (const raw of [2, 3, 4, 6, 7, 8, 9]) {
      expect(slaOfPriority(raw)).toBe('medium');
    }
  });

  it('ranks the strictest tier first and the inherited one last', () => {
    expect(slaRank('high')).toBeLessThan(slaRank('medium'));
    expect(slaRank('medium')).toBeLessThan(slaRank('low'));
    expect(slaRank('low')).toBeLessThan(slaRank('inherit'));
  });
});
