DELETE FROM api_keys
WHERE id IN (3001, 3002, 3003, 3004)
   OR user_id IN (
        SELECT id FROM users
        WHERE id IN (1001, 1002, 1003, 1004, 1005, 1006)
           OR keycloak_id IN (
                '00000000-0000-0000-0000-000000001001',
                '00000000-0000-0000-0000-000000001002',
                '00000000-0000-0000-0000-000000001003',
                '33333333-3333-3333-3333-333333333333',
                '44444444-4444-4444-4444-444444444444'
           )
           OR lower(email) IN ('legacy-admin@test.com', 'fresh@tum.de', 'newbie@tum.de')
   );
DELETE FROM team_members
WHERE team_id IN (2001, 2002)
   OR user_id IN (
        SELECT id FROM users
        WHERE id IN (1001, 1002, 1003, 1004, 1005, 1006)
           OR keycloak_id IN (
                '00000000-0000-0000-0000-000000001001',
                '00000000-0000-0000-0000-000000001002',
                '00000000-0000-0000-0000-000000001003',
                '33333333-3333-3333-3333-333333333333',
                '44444444-4444-4444-4444-444444444444'
           )
           OR lower(email) IN ('legacy-admin@test.com', 'fresh@tum.de', 'newbie@tum.de')
   );
DELETE FROM teams WHERE id IN (2001, 2002);
DELETE FROM users
WHERE id IN (1001, 1002, 1003, 1004, 1005, 1006)
   OR keycloak_id IN (
        '00000000-0000-0000-0000-000000001001',
        '00000000-0000-0000-0000-000000001002',
        '00000000-0000-0000-0000-000000001003',
        '33333333-3333-3333-3333-333333333333',
        '44444444-4444-4444-4444-444444444444'
   )
   OR lower(email) IN ('legacy-admin@test.com', 'fresh@tum.de', 'newbie@tum.de');

INSERT INTO users (id, username, prename, name, role, email, keycloak_id, last_synced_at)
VALUES (1001, 'testuser', 'Test', 'User', 'app_developer', 'test@test.com',
        '00000000-0000-0000-0000-000000001001', NOW());

INSERT INTO users (id, username, prename, name, role, email, keycloak_id, last_synced_at)
VALUES (1002, 'adminuser', 'Admin', 'User', 'app_admin', 'admin@test.com',
        '00000000-0000-0000-0000-000000001002', NOW());

INSERT INTO users (id, username, prename, name, role, keycloak_id, last_synced_at)
VALUES (1003, 'logosadmin', '', '', 'logos_admin', '00000000-0000-0000-0000-000000001003', NOW());

-- Deactivated user: must be hidden from user listings and team-member lists.
INSERT INTO users (id, username, prename, name, role, email, keycloak_id, last_synced_at, is_active)
VALUES (1004, 'inactiveuser', 'Inactive', 'User', 'app_developer', 'inactive@test.com',
        '00000000-0000-0000-0000-000000001004', NOW(), false);

-- Manually created user (no keycloak_id): identity, role and existence are
-- Logos-owned, so it stays fully editable and deletable. Kept teamless so it
-- does not perturb member/user counts asserted elsewhere.
INSERT INTO users (id, username, prename, name, role, email)
VALUES (1005, 'manualuser', 'Manual', 'User', 'app_developer', 'manual@test.com');

INSERT INTO teams (id, name) VALUES (2001, 'test-team');

INSERT INTO team_members (user_id, team_id, is_owner)
VALUES (1001, 2001, true);

INSERT INTO team_members (user_id, team_id, is_owner)
VALUES (1002, 2001, true);

-- logos_admin holds a key through team membership (no more team-less keys).
INSERT INTO team_members (user_id, team_id, is_owner)
VALUES (1003, 2001, false);

-- Deactivated user is a member but must not surface in member lists/counts.
INSERT INTO team_members (user_id, team_id, is_owner)
VALUES (1004, 2001, false);

INSERT INTO api_keys (id, key_value, name, key_type, user_id, team_id, is_active)
VALUES (3001, 'dev-key-1', 'dev key', 'developer', 1001, 2001, true);

INSERT INTO api_keys (id, key_value, name, key_type, user_id, team_id, is_active)
VALUES (3002, 'service-key-no-user', 'svc key', 'application', NULL, NULL, true);

INSERT INTO api_keys (id, key_value, name, key_type, user_id, team_id, is_active)
VALUES (3003, 'admin-key-1', 'admin key', 'developer', 1002, 2001, true);

INSERT INTO api_keys (id, key_value, name, key_type, user_id, team_id, is_active)
VALUES (3004, 'logos-admin-key', 'logos admin key', 'developer', 1003, 2001, true);

-- Keycloak-managed team (linked to a Keycloak group) and a Keycloak-sourced
-- membership: the team's name/existence and this membership are Keycloak-owned,
-- so they cannot be renamed, deleted or removed through the admin API.
INSERT INTO teams (id, name, keycloak_group) VALUES (2002, 'kc-team', 'kc-team-group');

INSERT INTO users (id, username, prename, name, role, email, keycloak_id, last_synced_at)
VALUES (1006, 'kcmember', 'KC', 'Member', 'app_developer', 'kcmember@test.com',
        '00000000-0000-0000-0000-000000001006', NOW());

INSERT INTO team_members (user_id, team_id, is_owner, source)
VALUES (1006, 2002, false, 'KEYCLOAK');
