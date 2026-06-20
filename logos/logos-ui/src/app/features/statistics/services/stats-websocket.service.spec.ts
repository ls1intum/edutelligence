import { vramDayString, buildStatsWsUrl } from './stats-websocket.service';

describe('stats websocket helpers', () => {
  it('vramDayString returns "all" for negative offset', () => {
    expect(vramDayString(-1)).toBe('all');
  });

  it('vramDayString returns a YYYY-MM-DD string for offset 0', () => {
    expect(vramDayString(0)).toMatch(/^\d{4}-\d{2}-\d{2}$/);
  });

  it('buildStatsWsUrl embeds the encoded key and v2 path', () => {
    const url = buildStatsWsUrl('a b/c');
    expect(url).toContain('/api/ws/stats/v2?key=');
    expect(url).toContain(encodeURIComponent('a b/c'));
  });
});
