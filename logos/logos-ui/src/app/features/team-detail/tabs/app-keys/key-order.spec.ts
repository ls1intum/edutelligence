import { loadKeyOrder, orderRank, saveKeyOrder } from './key-order';

/**
 * The manual drag order of a team's application keys.
 *
 * It is a display preference with no server side, so the two things that must
 * hold are that a key the stored order has never seen still appears (rather
 * than being dropped or jumping to the top), and that unreadable storage
 * degrades to the server order instead of throwing inside the row sort.
 */
describe('application key manual order', () => {
  const TEAM = 42;

  afterEach(() => localStorage.clear());

  it('round-trips an order through storage', () => {
    saveKeyOrder(TEAM, [3, 1, 2]);
    expect(loadKeyOrder(TEAM)).toEqual([3, 1, 2]);
  });

  it('keeps the order of each team separate', () => {
    saveKeyOrder(TEAM, [3, 1]);
    expect(loadKeyOrder(TEAM + 1)).toEqual([]);
  });

  it('falls back to the server order when nothing is stored', () => {
    expect(loadKeyOrder(TEAM)).toEqual([]);
  });

  it('ignores stored data that is not a list of key ids', () => {
    localStorage.setItem('logos.app-keys.order.' + TEAM, '{"not":"an array"}');
    expect(loadKeyOrder(TEAM)).toEqual([]);

    localStorage.setItem('logos.app-keys.order.' + TEAM, 'not json at all');
    expect(loadKeyOrder(TEAM)).toEqual([]);
  });

  it('ranks stored keys by their stored position', () => {
    const order = [30, 10, 20];
    expect(orderRank(order, 30, 0)).toBe(0);
    expect(orderRank(order, 10, 1)).toBe(1);
    expect(orderRank(order, 20, 2)).toBe(2);
  });

  it('sorts a key the stored order never saw after every stored one, in server order', () => {
    const order = [30, 10];
    // A key created after the order was saved: it keeps its server position
    // relative to other unknown keys instead of collapsing to the same rank.
    const first = orderRank(order, 99, 0);
    const second = orderRank(order, 98, 1);
    expect(first).toBeGreaterThan(orderRank(order, 10, 1));
    expect(second).toBeGreaterThan(first);
  });
});
