/**
 * Shared constants for the browser tier.
 *
 * The accounts come from `logos/keycloak/tum-realm.json`, the same realm the
 * dev stack imports — so a spec that logs in here is exercising the role
 * mapping an operator actually gets, not a test-only identity.
 */

export const STORAGE_STATE = './.playwright/admin-state.json';

export const ADMIN_USER = {
  username: 'tobias.wasner',
  password: 'password',
  role: 'logos_admin',
};

export const DEVELOPER_USER = {
  username: 'henriette.huhn',
  password: 'password',
  role: 'app_developer',
};

/** A user seeded with no roles at all — the no-access screens depend on it. */
export const NO_ROLE_USER = {
  username: 'pech.vogel',
  password: 'password',
};

/**
 * The simulated fleet, as `harness/stack/docker-compose.e2e.yaml` defines it.
 * The UI's hardware panels render these numbers, so a spec can assert the
 * browser is showing what the nodes actually reported rather than a placeholder.
 */
export const SIMULATED_FLEET = [
  { gpu: 'NVIDIA L40S', count: 2, totalVramMb: 46068 * 2 },
  { gpu: 'NVIDIA GeForce RTX 2080 Ti', count: 1, totalVramMb: 11264 },
];
