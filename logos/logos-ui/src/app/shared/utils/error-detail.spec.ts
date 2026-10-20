import { errorDetail } from './error-detail';

describe('errorDetail', () => {
  it('reads the detail the controllers send', () => {
    expect(errorDetail({ error: { detail: 'Team not found' } })).toBe('Team not found');
  });

  it('reads the error the global exception handler sends', () => {
    expect(errorDetail({ error: { error: "'itg-admin' grants a platform role" } }))
      .toBe("'itg-admin' grants a platform role");
  });

  it('prefers detail when a response carries both', () => {
    expect(errorDetail({ error: { detail: 'first', error: 'second' } })).toBe('first');
  });

  it('falls back to null for responses without a message', () => {
    expect(errorDetail({ error: { detail: '  ' } })).toBeNull();
    expect(errorDetail({ error: 'plain text body' })).toBeNull();
    expect(errorDetail({ status: 500 })).toBeNull();
    expect(errorDetail(new Error('network'))).toBeNull();
    expect(errorDetail(null)).toBeNull();
    expect(errorDetail(undefined)).toBeNull();
  });
});
