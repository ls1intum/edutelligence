INSERT INTO users (id, username, prename, name, role, email, keycloak_id, last_synced_at)
VALUES (1001, 'testuser', 'Test', 'User', 'app_developer', 'test@test.com',
        '00000000-0000-0000-0000-000000001001', NOW());

INSERT INTO users (id, username, prename, name, role, email, keycloak_id, last_synced_at)
VALUES (1002, 'adminuser', 'Admin', 'User', 'app_admin', 'admin@test.com',
        '00000000-0000-0000-0000-000000001002', NOW());

INSERT INTO users (id, username, prename, name, role, keycloak_id, last_synced_at)
VALUES (1003, 'logosadmin', '', '', 'logos_admin', '00000000-0000-0000-0000-000000001003', NOW());

INSERT INTO teams (id, name) VALUES (2001, 'test-team');

INSERT INTO team_members (user_id, team_id, is_owner)
VALUES (1001, 2001, true);

INSERT INTO team_members (user_id, team_id, is_owner)
VALUES (1002, 2001, true);

INSERT INTO api_keys (id, key_value, name, key_type, user_id, team_id, is_active)
VALUES (3001, 'dev-key-1', 'dev key', 'developer', 1001, 2001, true);

INSERT INTO api_keys (id, key_value, name, key_type, user_id, team_id, is_active)
VALUES (3002, 'service-key-no-user', 'svc key', 'application', NULL, NULL, true);

INSERT INTO api_keys (id, key_value, name, key_type, user_id, is_active)
VALUES (3003, 'admin-key-1', 'admin key', 'developer', 1002, true);

INSERT INTO api_keys (id, key_value, name, key_type, user_id, is_active)
VALUES (3004, 'logos-admin-key', 'logos admin key', 'developer', 1003, true);
