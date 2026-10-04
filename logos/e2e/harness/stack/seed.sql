-- Deterministic bootstrap for the E2E stack.
--
-- The dev stack normally grows its first admin through a Keycloak login, which
-- is interactive and gives a different key every time. The E2E tiers need a key
-- that is known before the stack starts (the simulated nodes register with it),
-- so this seeds the same rows that flow would produce — and nothing else, so
-- tests still exercise the real provider-registration path rather than a
-- pre-registered provider.
--
-- Applied after Liquibase has migrated the schema. Idempotent: re-running it
-- against a warm volume is a no-op.

INSERT INTO teams (name)
SELECT 'e2e'
WHERE NOT EXISTS (SELECT 1 FROM teams WHERE name = 'e2e');

INSERT INTO users (username, prename, name, role, email)
SELECT 'e2e.admin', 'E2E', 'Admin', 'logos_admin', 'e2e-admin@logos.invalid'
WHERE NOT EXISTS (SELECT 1 FROM users WHERE username = 'e2e.admin');

INSERT INTO users (username, prename, name, role, email)
SELECT 'e2e.developer', 'E2E', 'Developer', 'app_developer', 'e2e-dev@logos.invalid'
WHERE NOT EXISTS (SELECT 1 FROM users WHERE username = 'e2e.developer');

INSERT INTO team_members (user_id, team_id, is_owner)
SELECT u.id, t.id, true
FROM users u, teams t
WHERE u.username = 'e2e.admin' AND t.name = 'e2e'
  AND NOT EXISTS (SELECT 1 FROM team_members m WHERE m.user_id = u.id AND m.team_id = t.id);

INSERT INTO team_members (user_id, team_id, is_owner)
SELECT u.id, t.id, false
FROM users u, teams t
WHERE u.username = 'e2e.developer' AND t.name = 'e2e'
  AND NOT EXISTS (SELECT 1 FROM team_members m WHERE m.user_id = u.id AND m.team_id = t.id);

-- The admin key registers worker nodes (root-only endpoint).
INSERT INTO api_keys (key_value, name, key_type, team_id, user_id, is_active)
SELECT 'lg-e2e-admin-key', 'e2e-admin', 'developer', t.id, u.id, true
FROM users u, teams t
WHERE u.username = 'e2e.admin' AND t.name = 'e2e'
  AND NOT EXISTS (SELECT 1 FROM api_keys WHERE key_value = 'lg-e2e-admin-key');

-- The developer key is what the client tier sends: an ordinary key with no
-- elevated role, so an accidental privilege leak shows up as a test failure.
INSERT INTO api_keys (key_value, name, key_type, team_id, user_id, is_active)
SELECT 'lg-e2e-developer-key', 'e2e-developer', 'developer', t.id, u.id, true
FROM users u, teams t
WHERE u.username = 'e2e.developer' AND t.name = 'e2e'
  AND NOT EXISTS (SELECT 1 FROM api_keys WHERE key_value = 'lg-e2e-developer-key');
