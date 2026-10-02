-- Seed data for the gateway concurrency benchmark.
-- Run AFTER the Liquibase migration, against an empty logosdb:
--   psql "$LOGOS_DB_URL" -f seed.sql
--
-- Idempotent: deletes its own rows first (matched by marker ids), so it can
-- be re-run without touching migration-seeded rows.
--
-- base_url below (host.docker.internal:9100) matches fake_cloud_upstream.py's
-- default LOGOS_BENCH_GW_UPSTREAM_PORT. If you override that port, update the
-- provider row here too (same coupling as ../per_request_overhead/seed.sql
-- has with its mock lane port).

\set ON_ERROR_STOP on

BEGIN;

-- ---------------------------------------------------------------------------
-- Clean up a previous seed (FK-safe order)
-- ---------------------------------------------------------------------------
DELETE FROM team_provider_permissions WHERE team_id = 501;
DELETE FROM team_model_permissions    WHERE team_id = 501;
DELETE FROM model_provider            WHERE provider_id = 501;
DELETE FROM api_key_provider_permissions WHERE api_key_id = 501;
DELETE FROM api_key_model_permissions    WHERE api_key_id = 501;
DELETE FROM api_keys          WHERE id = 501;
DELETE FROM team_members      WHERE team_id = 501;
DELETE FROM teams             WHERE id = 501;
DELETE FROM providers         WHERE id = 501;
DELETE FROM models            WHERE id = 501;
DELETE FROM users             WHERE id = 501;

-- ---------------------------------------------------------------------------
-- User + team. Rate limits and budget MUST be NULL: the benchmark's whole
-- point is to find the gateway's own concurrency ceiling (the Spring task
-- executor pool), not an incidental team/budget limit hit first.
-- ---------------------------------------------------------------------------
INSERT INTO users (id, username, prename, name, email, role)
VALUES (501, 'bench-gw-user', 'B', 'Bench Gateway User', 'bench-gw-user@bench.test', 'app_developer');

INSERT INTO teams (
    id, name,
    default_cloud_rpm_limit, default_cloud_tpm_limit,
    default_local_rpm_limit, default_local_tpm_limit,
    default_monthly_budget_micro_cents, team_monthly_budget_micro_cents
)
VALUES (501, 'bench-gw-team', NULL, NULL, NULL, NULL, NULL, NULL);

INSERT INTO team_members (user_id, team_id, is_owner)
VALUES (501, 501, true);

-- ---------------------------------------------------------------------------
-- API key (plain developer key, team permissions — no custom overrides).
-- ---------------------------------------------------------------------------
INSERT INTO api_keys (
    id, key_value, name, key_type, team_id, user_id, environment, log,
    settings, default_priority, is_active, use_custom_permissions
)
VALUES (
    501, 'lg-bench-gw-0000', 'bench-gw-key', 'developer', 501, 501, 'test', 'BILLING',
    '{}'::jsonb, 1, true, false
);

-- ---------------------------------------------------------------------------
-- Model + cloud provider, no per-model endpoint override (NULL): the URL
-- builder falls back to base_url + inbound path, i.e. exactly
-- http://host.docker.internal:9100/v1/chat/completions — a plain
-- OpenAI-compatible endpoint, no Azure deployment-path handling needed.
-- ---------------------------------------------------------------------------
INSERT INTO models (id, name, description)
VALUES (501, 'bench-cloud-model', 'Gateway concurrency benchmark model');

INSERT INTO providers (
    id, name, base_url, provider_type, cloud_provider_type,
    privacy_level, auth_name, auth_format, api_key
)
VALUES (
    501, 'bench-cloud-upstream', 'http://host.docker.internal:9100', 'cloud', 'openai',
    'CLOUD_IN_EU_BY_US_PROVIDER', 'Authorization', 'Bearer {api_key}', 'bench-upstream-key'
);

INSERT INTO model_provider (id, provider_id, model_id) VALUES (501, 501, 501);

-- Permissions for the developer key's team.
INSERT INTO team_model_permissions (team_id, model_id) VALUES (501, 501);
INSERT INTO team_provider_permissions (team_id, provider_id) VALUES (501, 501);

-- ---------------------------------------------------------------------------
-- Keep SERIAL sequences ahead of the explicit ids (harmless if another seed
-- already pushed them further).
-- ---------------------------------------------------------------------------
SELECT setval('users_id_seq', GREATEST(501, (SELECT last_value FROM users_id_seq)));
SELECT setval('teams_id_seq', GREATEST(501, (SELECT last_value FROM teams_id_seq)));
SELECT setval('api_keys_id_seq', GREATEST(501, (SELECT last_value FROM api_keys_id_seq)));
SELECT setval('models_id_seq', GREATEST(501, (SELECT last_value FROM models_id_seq)));
SELECT setval('providers_id_seq', GREATEST(501, (SELECT last_value FROM providers_id_seq)));
SELECT setval('model_provider_id_seq', GREATEST(501, (SELECT last_value FROM model_provider_id_seq)));

COMMIT;
