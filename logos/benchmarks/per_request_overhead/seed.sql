-- Seed data for the per-request overhead benchmark (issue #980).
-- Run AFTER the Liquibase migration, against an empty logosdb:
--   psql "$LOGOS_DB_URL" -f seed.sql
--
-- Idempotent: deletes its own rows first (matched by marker values), so it
-- can be re-run without touching migration-seeded rows (e.g. the billed_*
-- token_types from changelog 023).

\set ON_ERROR_STOP on

BEGIN;

-- ---------------------------------------------------------------------------
-- Clean up a previous seed (FK-safe order)
-- ---------------------------------------------------------------------------
DELETE FROM team_provider_permissions WHERE team_id IN (1, 2);
DELETE FROM team_model_permissions    WHERE team_id IN (1, 2);
DELETE FROM logosnode_provider_keys   WHERE provider_id IN (1, 2);
DELETE FROM model_provider            WHERE provider_id IN (1, 2);
DELETE FROM model_aliases             WHERE model_id IN (1, 2);
DELETE FROM api_key_provider_permissions WHERE api_key_id IN (1, 2);
DELETE FROM api_key_model_permissions    WHERE api_key_id IN (1, 2);
DELETE FROM api_keys          WHERE id IN (1, 2);
DELETE FROM team_members      WHERE team_id IN (1, 2);
DELETE FROM teams             WHERE id IN (1, 2);
DELETE FROM providers         WHERE id IN (1, 2);
DELETE FROM models            WHERE id IN (1, 2);
DELETE FROM users             WHERE id IN (1, 2);
DELETE FROM token_types       WHERE name IN ('prompt_tokens', 'completion_tokens', 'total_tokens');

-- ---------------------------------------------------------------------------
-- Users (user 1: plain developer, user 2: logos_admin for the O3 bypass case)
-- ---------------------------------------------------------------------------
INSERT INTO users (id, username, prename, name, email, role)
VALUES
    (1, 'bench-user', 'B', 'Bench User', 'bench-user@bench.test', 'app_developer'),
    (2, 'bench-admin', 'A', 'Bench Admin', 'bench-admin@bench.test', 'logos_admin');

-- ---------------------------------------------------------------------------
-- Team. Rate limits MUST be NULL: the DDL defaults are 5 RPM / 10000 TPM,
-- which would make the benchmark receive 429 after five requests. NULL
-- limits disable the local rate limiter entirely for the bench team.
-- ---------------------------------------------------------------------------
INSERT INTO teams (
    id, name,
    default_cloud_rpm_limit, default_cloud_tpm_limit,
    default_local_rpm_limit, default_local_tpm_limit,
    default_monthly_budget_micro_cents, team_monthly_budget_micro_cents
)
VALUES (1, 'bench-team', NULL, NULL, NULL, NULL, NULL, NULL);

INSERT INTO team_members (user_id, team_id, is_owner)
VALUES (1, 1, true), (2, 1, true);

-- ---------------------------------------------------------------------------
-- API keys
--   key 1: the benchmark key (developer, team permissions, BILLING log level)
--   key 2: admin key (logos_admin user) — exercises the permission bypass
-- ---------------------------------------------------------------------------
INSERT INTO api_keys (
    id, key_value, name, key_type, team_id, user_id, environment, log,
    settings, default_priority, is_active, use_custom_permissions
)
VALUES
    (1, 'lg-bench-0000', 'bench-key', 'developer', 1, 1, 'test', 'BILLING',
     '{}'::jsonb, 1, true, false),
    (2, 'lg-bench-admin', 'bench-admin-key', 'developer', 1, 2, 'test', 'BILLING',
     '{}'::jsonb, 1, true, false);

-- ---------------------------------------------------------------------------
-- Model + logosnode provider.
-- providers.api_key IS the shared_key the worker posts to
-- /logosdb/providers/logosnode/auth to register its WebSocket session.
-- base_url is NOT NULL for every provider; for logosnode it is inert
-- (routing goes through the worker registry), so the mock lane URL is used.
-- ---------------------------------------------------------------------------
INSERT INTO models (id, name, description)
VALUES (1, 'bench-local-model', 'Benchmark warm model');

INSERT INTO providers (
    id, name, base_url, provider_type, cloud_provider_type,
    privacy_level, auth_name, auth_format, api_key
)
VALUES (
    1, 'bench-worker', 'http://127.0.0.1:11436', 'logosnode', NULL,
    'LOCAL', '', '{}', 'lg-worker-shared-0000'
);

INSERT INTO model_provider (id, provider_id, model_id) VALUES (1, 1, 1);
INSERT INTO logosnode_provider_keys (provider_id) VALUES (1);

-- Permissions for the developer key's team (the admin key needs none).
INSERT INTO team_model_permissions (team_id, model_id) VALUES (1, 1);
INSERT INTO team_provider_permissions (team_id, provider_id) VALUES (1, 1);

-- ---------------------------------------------------------------------------
-- Token types used by the mock lane's usage block (the runtime auto-creates
-- missing types as well; seeding them keeps the batched-lookup path warm and
-- deterministic).
-- ---------------------------------------------------------------------------
INSERT INTO token_types (name, description)
VALUES
    ('prompt_tokens', 'Prompt tokens'),
    ('completion_tokens', 'Completion tokens'),
    ('total_tokens', 'Total tokens')
ON CONFLICT (name) DO NOTHING;

-- ---------------------------------------------------------------------------
-- Keep SERIAL sequences ahead of the explicit ids.
-- ---------------------------------------------------------------------------
SELECT setval('users_id_seq', 2);
SELECT setval('teams_id_seq', 1);
SELECT setval('api_keys_id_seq', 2);
SELECT setval('models_id_seq', 1);
SELECT setval('providers_id_seq', 1);
SELECT setval('model_provider_id_seq', 1);
SELECT setval('logosnode_provider_keys_id_seq', 1);

COMMIT;
