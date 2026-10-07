import { describe, expect, it } from 'vitest';
import { PublicStats, PublicTeamStats } from './public-stats.service';
import {
  MAX_NAMED_TEAM_SLICES,
  OTHER_SLICE_COLOR,
  buildPieGeometry,
  formatAverage,
  formatCount,
  keyTypeSlices,
  laneSlices,
  pieSlicePath,
  teamSlices,
  ChartSlice,
} from './public-stats.utils';

function stats(overrides: Partial<PublicStats> = {}): PublicStats {
  return {
    students: 5,
    teams: 2,
    successful_requests: 5,
    average_requests_per_user: 1.2,
    requests_per_team: [],
    requests_by_key_type: { developer: 3, application: 2, service: 0 },
    local_cloud_requests: { local: 1, cloud: 4 },
    ...overrides,
  };
}

// L x1 y1 A r r 0 largeArc sweep x2 y2 Z — groups 1-2 the start point, 5 the
// large-arc flag, 7-8 the end point. The literal 0 is the SVG arc rotation.
const WEDGE = /L ([^ ]+) ([^ ]+) A ([^ ]+) ([^ ]+) 0 ([^ ]+) ([^ ]+) ([^ ]+) ([^ ]+) Z/;

describe('pieSlicePath', () => {
  it('starts at the top and sweeps clockwise', () => {
    // A quarter slice from 12 o'clock ends at 3 o'clock.
    const path = pieSlicePath(100, 100, 92, 0, Math.PI / 2);
    expect(path).toMatch(/^M 100 100 L /);
    expect(path).toContain(' A 92 92 0 0 1 ');
    expect(path).toContain('192 100');
    expect(path).toMatch(/Z$/);
  });

  it('clamps a full circle just short of 360° so the arc does not collapse', () => {
    const path = pieSlicePath(100, 100, 92, 0, Math.PI * 2);
    const m = path.match(WEDGE);
    expect(m).not.toBeNull();
    // Large-arc flag set, and the wedge is not degenerate: the end point is a
    // hair before the start point, not on top of it.
    expect(m![5]).toBe('1');
    expect(m![1] + ' ' + m![2]).not.toEqual(m![7] + ' ' + m![8]);
  });

  it('flags large arcs past a half turn', () => {
    expect(pieSlicePath(0, 0, 10, 0, Math.PI * 1.5)).toContain(' A 10 10 0 1 1 ');
    expect(pieSlicePath(0, 0, 10, 0, Math.PI / 2)).toContain(' A 10 10 0 0 1 ');
  });
});

describe('buildPieGeometry', () => {
  const slices: ChartSlice[] = [
    { key: 'a', label: 'A', value: 3, color: 'var(--series-1)', hidden: false },
    { key: 'b', label: 'B', value: 1, color: 'var(--series-2)', hidden: false },
  ];

  it('computes shares of the visible total', () => {
    const geometry = buildPieGeometry(slices);
    expect(geometry.map((g) => g.percent)).toEqual([75, 25]);
    expect(geometry.every((g) => g.path.startsWith('M 100 100 L '))).toBe(true);
  });

  it('drops hidden and zero-value slices and re-partitions the rest', () => {
    const hidden: ChartSlice[] = [...slices, { key: 'c', label: 'C', value: 0, color: 'x', hidden: false }].map(
      (s) => ({ ...s })
    );
    hidden[0].hidden = true;
    const geometry = buildPieGeometry(hidden);
    expect(geometry.map((g) => g.slice.key)).toEqual(['b']);
    expect(geometry[0].percent).toBe(100);
  });

  it('returns nothing when every slice is hidden', () => {
    const allHidden = slices.map((s) => ({ ...s, hidden: true }));
    expect(buildPieGeometry(allHidden)).toEqual([]);
  });

  it('keeps slice order and the percentages add up to the whole pie', () => {
    const geometry = buildPieGeometry(slices);
    expect(geometry.map((g) => g.slice.key)).toEqual(['a', 'b']);
    const sum = geometry.reduce((acc, g) => acc + g.percent, 0);
    expect(sum).toBeGreaterThanOrEqual(99); // rounding may lose at most a point
    expect(sum).toBeLessThanOrEqual(101);
  });
});

describe('teamSlices', () => {
  it('orders by request count, then name, and assigns colors from the fixed slot order', () => {
    const teams: PublicTeamStats[] = [
      { team_id: 1, team_name: 'Alpha', requests: 5 },
      { team_id: 2, team_name: 'Beta', requests: 9 },
      { team_id: 3, team_name: 'Gamma', requests: 9 },
    ];
    const slices = teamSlices(teams);
    expect(slices.map((s) => s.key)).toEqual(['2', '3', '1']); // Beta, Gamma (name tie-break), Alpha
    expect(slices.map((s) => s.color)).toEqual([
      'var(--series-1)',
      'var(--series-2)',
      'var(--series-3)',
    ]);
  });

  it('names a team-less slice "No team" under a stable key', () => {
    const slices = teamSlices([{ team_id: null, team_name: null, requests: 2 }]);
    expect(slices).toEqual([
      { key: 'none', label: 'No team', value: 2, color: 'var(--series-1)', hidden: false },
    ]);
  });

  it('folds teams past the cap into a hueless "Other teams" slice', () => {
    const teams: PublicTeamStats[] = Array.from({ length: MAX_NAMED_TEAM_SLICES + 2 }, (_, i) => ({
      team_id: i + 1,
      team_name: `Team ${i + 1}`,
      requests: i + 1,
    }));
    const slices = teamSlices(teams);
    expect(slices).toHaveLength(MAX_NAMED_TEAM_SLICES + 1);
    const other = slices[slices.length - 1];
    expect(other).toEqual({
      key: 'other',
      label: 'Other teams',
      value: 3, // teams 2 and 1 — the two that fell past the cap
      color: OTHER_SLICE_COLOR,
      hidden: false,
    });
    // No generated hue: the named slices stop at the last slot.
    expect(slices[MAX_NAMED_TEAM_SLICES - 1].color).toBe(`var(--series-${MAX_NAMED_TEAM_SLICES})`);
  });

  it('keeps colors stable when a team is hidden', () => {
    const teams: PublicTeamStats[] = [
      { team_id: 1, team_name: 'Alpha', requests: 5 },
      { team_id: 2, team_name: 'Beta', requests: 9 },
      { team_id: 3, team_name: 'Gamma', requests: 7 },
    ];
    const before = teamSlices(teams);
    const after = before.map((s) => (s.key === '2' ? { ...s, hidden: true } : s));
    expect(after.map((s) => s.color)).toEqual(before.map((s) => s.color));
  });

  it('ignores zero-request teams', () => {
    expect(teamSlices([{ team_id: 1, team_name: 'Idle', requests: 0 }])).toEqual([]);
  });
});

describe('keyTypeSlices and laneSlices', () => {
  it('maps the key types with members first and keeps fixed slots', () => {
    const slices = keyTypeSlices(stats());
    expect(slices.map((s) => [s.key, s.value, s.color])).toEqual([
      ['developer', 3, 'var(--series-1)'],
      ['application', 2, 'var(--series-2)'],
      ['service', 0, 'var(--series-3)'],
    ]);
  });

  it('adds an unknown key-type slice only when deleted keys contribute', () => {
    expect(keyTypeSlices(stats({ requests_by_key_type: { developer: 1, application: 0, service: 0, unknown: 0 } }))).toHaveLength(
      3
    );
    const withUnknown = keyTypeSlices(
      stats({ requests_by_key_type: { developer: 1, application: 0, service: 0, unknown: 2 } })
    );
    expect(withUnknown[withUnknown.length - 1]).toEqual({
      key: 'unknown',
      label: 'Unknown key',
      value: 2,
      color: OTHER_SLICE_COLOR,
      hidden: false,
    });
  });

  it('maps the lanes with local first', () => {
    const slices = laneSlices(stats());
    expect(slices.map((s) => [s.key, s.value, s.color])).toEqual([
      ['local', 1, 'var(--series-1)'],
      ['cloud', 4, 'var(--series-2)'],
    ]);
  });

  it('adds an unknown lane slice only when deleted providers contribute', () => {
    const withUnknown = laneSlices(stats({ local_cloud_requests: { local: 1, cloud: 1, unknown: 3 } }));
    expect(withUnknown[withUnknown.length - 1]).toEqual({
      key: 'unknown',
      label: 'Unknown lane',
      value: 3,
      color: OTHER_SLICE_COLOR,
      hidden: false,
    });
  });
});

describe('formatters', () => {
  it('groups counts and trims average decimals', () => {
    expect(formatCount(1234567)).toBe(new Intl.NumberFormat().format(1234567));
    expect(formatCount(0)).toBe('0');
    expect(formatAverage(1)).toBe('1');
    expect(formatAverage(1.2)).toBe('1.2');
    expect(formatAverage(1.234)).toBe('1.23');
  });
});
