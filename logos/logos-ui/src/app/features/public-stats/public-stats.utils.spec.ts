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
  windowLabel,
  ChartSlice,
  categorySlices,
  laneTokenSlices,
  modelSlices,
  monthLabel,
  trendPoints,
} from './public-stats.utils';
import { usageFields } from './public-stats.testing';

function stats(overrides: Partial<PublicStats> = {}): PublicStats {
  return {
    days: '30',
    students: 5,
    teams: 2,
    successful_requests: 5,
    average_requests_per_user: 1.2,
    requests_per_team: [],
    requests_by_key_type: { developer: 3, application: 2, service: 0 },
    local_cloud_requests: { local: 1, cloud: 4 },
    ...usageFields(),
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

describe('windowLabel', () => {
  it('labels rolling windows and all time', () => {
    expect(windowLabel('30')).toBe('last 30 days');
    expect(windowLabel('7')).toBe('last 7 days');
    expect(windowLabel('all')).toBe('all time');
  });
});

describe('keyTypeSlices and laneSlices', () => {
  it('maps the key types with members first and keeps fixed slots', () => {
    const slices = keyTypeSlices(stats());
    expect(slices.map((s) => [s.key, s.value, s.color])).toEqual([
      ['developer', 3, 'var(--duo-1)'],
      ['application', 2, 'var(--duo-2)'],
      ['service', 0, 'var(--duo-3)'],
    ]);
    expect(slices.find((s) => s.key === 'service')!.caption).toContain('automated backend jobs');
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
      caption: 'Requests whose API key was later deleted.',
      value: 2,
      color: OTHER_SLICE_COLOR,
      hidden: false,
    });
  });

  it('maps the lanes with local first', () => {
    const slices = laneSlices(stats());
    expect(slices.map((s) => [s.key, s.value, s.color])).toEqual([
      ['local', 1, 'var(--duo-1)'],
      ['cloud', 4, 'var(--duo-2)'],
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

describe('usage helpers', () => {
  it('splits tokens by lane like requests, with unknown only when present', () => {
    const slices = laneTokenSlices(stats({ ...usageFields({ local_cloud_tokens: { local: 70, cloud: 30 } }) }));
    expect(slices.map((s) => [s.key, s.value])).toEqual([
      ['local', 70],
      ['cloud', 30],
    ]);
  });

  it('names categories in order and folds uncategorized teams into the neutral slice', () => {
    const slices = categorySlices([
      { category: 'Research', teams: 3, requests: 50, tokens: 2_000_000 },
      { category: null, teams: 2, requests: 20, tokens: 1000 },
      { category: 'Teaching', teams: 1, requests: 10, tokens: 10 },
    ]);
    expect(slices.map((s) => s.label)).toEqual(['Research', 'Teaching', 'Uncategorized']);
    expect(slices[0].color).toBe('var(--series-1)');
    expect(slices[2].color).toBe(OTHER_SLICE_COLOR);
    expect(slices[0].caption).toContain('3 teams');
  });

  it('labels the model long tail and carries each token share', () => {
    const slices = modelSlices([
      { model: 'big', requests: 10, tokens: 75, other: false },
      { model: null, requests: 5, tokens: 25, other: true },
    ]);
    expect(slices.map((s) => s.label)).toEqual(['big', 'Other models']);
    expect(slices[0].caption).toBe('75% of tokens');
    expect(slices[1].color).toBe(OTHER_SLICE_COLOR);
  });

  it('reads months as short names and plots the chosen metric', () => {
    expect(monthLabel('2026-04')).toBe('Apr 2026');
    const months = [
      {
        month: '2026-08',
        teams: 2,
        persons: 5,
        students: 3,
        requests: 100,
        local_requests: 90,
        tokens: 1000,
        agent_sessions: 0,
        agent_users: 0,
      },
    ];
    expect(trendPoints(months, 'persons')).toEqual([{ key: '2026-08', label: 'Aug 2026', value: 5 }]);
    expect(trendPoints(months, 'tokens')[0].value).toBe(1000);
  });
});

