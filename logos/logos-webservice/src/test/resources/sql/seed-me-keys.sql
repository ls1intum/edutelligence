INSERT INTO users (id, username, prename, name, role, email, keycloak_id, last_synced_at)
VALUES (1101, 'alice', 'Alice', 'Dev', 'app_developer', 'alice@test.com',
        '00000000-0000-0000-0000-000000001101', NOW());

INSERT INTO users (id, username, prename, name, role, email, keycloak_id, last_synced_at)
VALUES (1102, 'bob', 'Bob', 'Dev', 'app_developer', 'bob@test.com',
        '00000000-0000-0000-0000-000000001102', NOW());

INSERT INTO teams (id, name, team_monthly_budget_micro_cents)
VALUES (2101, 'team-alpha', 1000000);

INSERT INTO team_members (user_id, team_id, is_owner)
VALUES (1101, 2101, true);

INSERT INTO team_members (user_id, team_id, is_owner)
VALUES (1102, 2101, false);

INSERT INTO api_keys (id, key_value, name, key_type, user_id, team_id, is_active, log, settings)
VALUES (3101, 'alice-key-1', 'alice-alpha-key', 'developer', 1101, 2101, true, 'BILLING', '{"budget_limit_micro_cents": 500000, "cloud_rpm_limit": 60}');

INSERT INTO api_keys (id, key_value, name, key_type, user_id, team_id, is_active, log, settings)
VALUES (3102, 'bob-key-1', 'bob-alpha-key', 'developer', 1102, 2101, true, 'BILLING', '{}');

INSERT INTO api_keys (id, key_value, name, key_type, user_id, team_id, is_active, log, settings)
VALUES (3103, 'svc-key-1', 'svc-key', 'application', NULL, 2101, true, 'BILLING', '{}');

INSERT INTO models (id, name, weight_latency, weight_accuracy, weight_cost, weight_quality)
VALUES (5101, 'test-model', 0, 0, 0, 0);

INSERT INTO providers (id, name, base_url, privacy_level, auth_name, auth_format)
VALUES (6101, 'test-provider', 'http://localhost', 'LOCAL', 'Authorization', 'Bearer {}');

INSERT INTO model_provider (id, provider_id, model_id)
VALUES (7101, 6101, 5101);

INSERT INTO team_model_permissions (team_id, model_id)
VALUES (2101, 5101);

INSERT INTO team_provider_permissions (team_id, provider_id)
VALUES (2101, 6101);
