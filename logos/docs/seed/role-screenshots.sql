-- Role-guide documentation seed for logos/docs.
--
-- Idempotent. Safe to re-run. Tags demo traffic with
-- environment = 'docs-role-screenshots' so a wipe is precise.
--
-- Prerequisite: log in once as tobias.wasner, alexandra.szuminska, and
-- henriette.huhn (password: password) so Keycloak sync has created the
-- users rows. See logos/docs/AGENTS.md.
--
-- Apply (screenshots compose example):
--   docker exec -i doks-db psql -U postgres -d logosdb < logos/docs/seed/role-screenshots.sql

BEGIN;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM users WHERE username = 'tobias.wasner')
       OR NOT EXISTS (SELECT 1 FROM users WHERE username = 'alexandra.szuminska')
       OR NOT EXISTS (SELECT 1 FROM users WHERE username = 'henriette.huhn')
    THEN
        RAISE EXCEPTION
            'required Keycloak users missing — log in once as tobias.wasner, alexandra.szuminska, and henriette.huhn, then re-run (see logos/docs/AGENTS.md)';
    END IF;
END $$;

-- ---------------------------------------------------------------------------
-- Wipe previous docs-role-screenshots run
-- ---------------------------------------------------------------------------
DELETE FROM usage_tokens
WHERE log_entry_id IN (
    SELECT id FROM log_entry WHERE environment = 'docs-role-screenshots'
);
DELETE FROM log_entry WHERE environment = 'docs-role-screenshots';

DELETE FROM batch_objects
WHERE upstream_id LIKE 'batch_docs_%'
   OR filename LIKE 'docs-role-screenshots%';

DELETE FROM agent_sessions
WHERE created_by = 'docs-role-screenshots';
DELETE FROM agent_workspaces
WHERE created_by = 'docs-role-screenshots';

DELETE FROM policies WHERE name IN (
    'Local-first routing', 'Cost saver for drafts', 'High-quality answers'
);

DELETE FROM model_aliases
WHERE model_id IN (SELECT id FROM models WHERE name IN (
    'llama-3.1-8b-instruct', 'qwen-2.5-72b-instruct', 'mistral-small-3.2-24b'
));
DELETE FROM model_capabilities
WHERE model_id IN (SELECT id FROM models WHERE name IN (
    'llama-3.1-8b-instruct', 'qwen-2.5-72b-instruct', 'mistral-small-3.2-24b'
));
DELETE FROM token_prices
WHERE model_id IN (SELECT id FROM models WHERE name IN (
    'llama-3.1-8b-instruct', 'qwen-2.5-72b-instruct', 'mistral-small-3.2-24b'
));
DELETE FROM team_model_permissions
WHERE model_id IN (SELECT id FROM models WHERE name IN (
    'llama-3.1-8b-instruct', 'qwen-2.5-72b-instruct', 'mistral-small-3.2-24b'
));
DELETE FROM team_provider_permissions
WHERE provider_id IN (SELECT id FROM providers WHERE name IN (
    'Docs Cloud (EU)', 'Docs Local Worker'
));
DELETE FROM model_provider
WHERE model_id IN (SELECT id FROM models WHERE name IN (
    'llama-3.1-8b-instruct', 'qwen-2.5-72b-instruct', 'mistral-small-3.2-24b'
))
   OR provider_id IN (SELECT id FROM providers WHERE name IN (
    'Docs Cloud (EU)', 'Docs Local Worker'
));
DELETE FROM models WHERE name IN (
    'llama-3.1-8b-instruct', 'qwen-2.5-72b-instruct', 'mistral-small-3.2-24b'
);
DELETE FROM providers WHERE name IN (
    'Docs Cloud (EU)', 'Docs Local Worker'
);

DELETE FROM api_keys WHERE name LIKE 'docs-role-%';
-- Keep an existing "Logos" team (common on long-lived DBs); only remove
-- memberships we added for the three screenshot users when re-seeding keys
-- would otherwise leave orphaned docs-role keys. Members stay.

-- Prefer a team named "Logos" if one already exists (matches existing shots);
-- otherwise create the docs team under that display name for a fresh DB.
INSERT INTO teams (
    name,
    default_cloud_rpm_limit, default_cloud_tpm_limit,
    default_local_rpm_limit, default_local_tpm_limit,
    default_monthly_budget_micro_cents, team_monthly_budget_micro_cents
)
SELECT
    'Logos',
    5, 10000,
    5, 10000,
    100000000,   -- $1.00 key default / month
    500000000    -- $5.00 team member budget / month
WHERE NOT EXISTS (SELECT 1 FROM teams WHERE name = 'Logos');

UPDATE teams SET
    default_cloud_rpm_limit = 5,
    default_cloud_tpm_limit = 10000,
    default_local_rpm_limit = 5,
    default_local_tpm_limit = 10000,
    default_monthly_budget_micro_cents = 100000000,
    team_monthly_budget_micro_cents = 500000000
WHERE name = 'Logos';

-- Members: Alexandra owns; Tobias + Henriette are members.
INSERT INTO team_members (user_id, team_id, is_owner)
SELECT u.id, t.id, (u.username = 'alexandra.szuminska')
FROM users u
CROSS JOIN teams t
WHERE t.name = 'Logos'
  AND u.username IN ('tobias.wasner', 'alexandra.szuminska', 'henriette.huhn')
ON CONFLICT (user_id, team_id) DO UPDATE
SET is_owner = EXCLUDED.is_owner;

-- Developer keys (one per user) + one application key for the team.
INSERT INTO api_keys (key_value, name, key_type, team_id, user_id, is_active, log, settings)
SELECT
    'lg-docs-' || u.username,
    'docs-role-' || u.username || '-key',
    'developer',
    t.id,
    u.id,
    true,
    'BILLING',
    jsonb_build_object(
        'budget_limit_micro_cents', 100000000,
        'cloud_rpm_limit', 5,
        'cloud_tpm_limit', 10000,
        'local_rpm_limit', 5,
        'local_tpm_limit', 10000
    )
FROM users u
CROSS JOIN teams t
WHERE t.name = 'Logos'
  AND u.username IN ('tobias.wasner', 'alexandra.szuminska', 'henriette.huhn')
  AND NOT EXISTS (
      SELECT 1 FROM api_keys k
      WHERE k.name = 'docs-role-' || u.username || '-key'
  );

INSERT INTO api_keys (key_value, name, key_type, team_id, user_id, is_active, log, settings)
SELECT
    'lg-docs-app-logos',
    'docs-role-logos-app-key',
    'application',
    t.id,
    NULL,
    true,
    'BILLING',
    '{}'::jsonb
FROM teams t
WHERE t.name = 'Logos'
  AND NOT EXISTS (SELECT 1 FROM api_keys WHERE name = 'docs-role-logos-app-key');

-- Providers + models (names match the committed shots' catalogue style).
INSERT INTO providers (name, base_url, provider_type, cloud_provider_type, privacy_level, auth_name, auth_format)
SELECT v.name, v.base_url, v.provider_type, v.cloud_provider_type, v.privacy_level, v.auth_name, v.auth_format
FROM (VALUES
    ('Docs Cloud (EU)', 'https://example.invalid/openai', 'cloud'::provider_type_enum,
     'azure'::cloud_provider_type_enum, 'CLOUD_IN_EU_BY_US_PROVIDER'::threshold_enum, 'api-key', '{}'),
    ('Docs Local Worker', 'http://logosnode.invalid', 'logosnode'::provider_type_enum,
     NULL::cloud_provider_type_enum, 'LOCAL'::threshold_enum, 'Authorization', 'Bearer {}')
) AS v(name, base_url, provider_type, cloud_provider_type, privacy_level, auth_name, auth_format)
WHERE NOT EXISTS (SELECT 1 FROM providers p WHERE p.name = v.name);

INSERT INTO models (name, weight_latency, weight_accuracy, weight_cost, weight_quality, tags, description)
SELECT v.*
FROM (VALUES
    ('llama-3.1-8b-instruct', 8, 8, 8, 8, 'chat,fast',
     'Small general-purpose chat model for everyday workloads.'),
    ('qwen-2.5-72b-instruct', 0, 0, 0, 0, 'chat,reasoning',
     'Large instruction-tuned model with strong reasoning.'),
    ('mistral-small-3.2-24b', -8, -8, -8, -8, 'chat,cost-efficient',
     'Balanced model for cost-efficient production traffic.')
) AS v(name, weight_latency, weight_accuracy, weight_cost, weight_quality, tags, description)
WHERE NOT EXISTS (SELECT 1 FROM models m WHERE m.name = v.name);

INSERT INTO model_capabilities (model_id, supports_function_calling, supports_vision, supports_reasoning)
SELECT m.id,
       true,
       (m.name LIKE 'mistral%'),
       (m.name LIKE 'qwen%')
FROM models m
WHERE m.name IN ('llama-3.1-8b-instruct', 'qwen-2.5-72b-instruct', 'mistral-small-3.2-24b')
  AND NOT EXISTS (SELECT 1 FROM model_capabilities c WHERE c.model_id = m.id);

INSERT INTO model_aliases (model_id, alias)
SELECT m.id, a.alias
FROM models m
JOIN (VALUES
    ('llama-3.1-8b-instruct', 'llama-3.1-8b'),
    ('qwen-2.5-72b-instruct', 'qwen-72b'),
    ('mistral-small-3.2-24b', 'mistral-3.2')
) AS a(model_name, alias) ON a.model_name = m.name
WHERE NOT EXISTS (
    SELECT 1 FROM model_aliases ma WHERE lower(ma.alias) = lower(a.alias)
);

INSERT INTO model_provider (provider_id, model_id)
SELECT p.id, m.id
FROM models m
CROSS JOIN providers p
WHERE m.name IN ('llama-3.1-8b-instruct', 'qwen-2.5-72b-instruct', 'mistral-small-3.2-24b')
  AND p.name = 'Docs Local Worker'
  AND NOT EXISTS (
      SELECT 1 FROM model_provider mp
      WHERE mp.model_id = m.id AND mp.provider_id = p.id
  );

INSERT INTO model_provider (provider_id, model_id)
SELECT p.id, m.id
FROM models m
CROSS JOIN providers p
WHERE m.name = 'llama-3.1-8b-instruct'
  AND p.name = 'Docs Cloud (EU)'
  AND NOT EXISTS (
      SELECT 1 FROM model_provider mp
      WHERE mp.model_id = m.id AND mp.provider_id = p.id
  );

INSERT INTO team_model_permissions (team_id, model_id)
SELECT t.id, m.id
FROM teams t
CROSS JOIN models m
WHERE t.name = 'Logos'
  AND m.name IN ('llama-3.1-8b-instruct', 'qwen-2.5-72b-instruct', 'mistral-small-3.2-24b')
ON CONFLICT DO NOTHING;

INSERT INTO team_provider_permissions (team_id, provider_id)
SELECT t.id, p.id
FROM teams t
CROSS JOIN providers p
WHERE t.name = 'Logos'
  AND p.name IN ('Docs Cloud (EU)', 'Docs Local Worker')
ON CONFLICT DO NOTHING;

INSERT INTO policies (
    name, description, threshold_privacy,
    threshold_latency, threshold_accuracy, threshold_cost, threshold_quality,
    priority, topic, team_id
)
SELECT v.name, v.description, v.privacy::threshold_enum,
       0, 0, 0, 0, v.priority, v.topic, t.id
FROM teams t
CROSS JOIN (VALUES
    ('Local-first routing', 'Route to self-hosted models when they can answer.', 'LOCAL', 1, 'default'),
    ('Cost saver for drafts', 'Prefer the cheapest models for drafting.', 'LOCAL', 2, 'drafting'),
    ('High-quality answers', 'Use the most accurate models for customer-facing work.', 'LOCAL', 3, 'customer-facing')
) AS v(name, description, privacy, priority, topic)
WHERE t.name = 'Logos'
  AND NOT EXISTS (SELECT 1 FROM policies p WHERE p.name = v.name);

-- Usage + finalized cost → billing chart, statistics KPIs, My Workspace bars, team budget.
INSERT INTO log_entry (
    request_id, api_key_id, model_id, provider_id, result_status,
    timestamp_request, timestamp_forwarding, time_at_first_token, timestamp_response,
    was_cold_start, queue_depth_at_enqueue, user_id, team_id, environment,
    rate_limit_admitted, cost_finalized, settled_cost_micro_cents
)
SELECT
    'docs-role-req-' || g.n,
    k.id,
    m.id,
    p.id,
    'success',
    date_trunc('day', now()) - (((g.n % 16) + 1) || ' days')::interval + ((g.n % 5) || ' hours')::interval,
    date_trunc('day', now()) - (((g.n % 16) + 1) || ' days')::interval + ((g.n % 5) || ' hours')::interval + interval '1 second',
    date_trunc('day', now()) - (((g.n % 16) + 1) || ' days')::interval + ((g.n % 5) || ' hours')::interval + interval '1.2 seconds',
    date_trunc('day', now()) - (((g.n % 16) + 1) || ' days')::interval + ((g.n % 5) || ' hours')::interval + interval '2 seconds',
    false,
    0,
    k.user_id,
    k.team_id,
    'docs-role-screenshots',
    true,
    true,
    100000 + (g.n * 7000)   -- ~$0.10–$0.20-ish micro-cents spread across the month
FROM generate_series(1, 48) AS g(n)
JOIN api_keys k ON k.name = 'docs-role-tobias.wasner-key'
JOIN models m ON m.name = 'llama-3.1-8b-instruct'
JOIN providers p ON p.name = 'Docs Cloud (EU)';

-- Recent in-window traffic so My Workspace rate-limit bars show used > 0.
INSERT INTO log_entry (
    request_id, api_key_id, model_id, provider_id, result_status,
    timestamp_request, timestamp_forwarding, time_at_first_token, timestamp_response,
    was_cold_start, queue_depth_at_enqueue, user_id, team_id, environment,
    rate_limit_admitted, cost_finalized, settled_cost_micro_cents
)
SELECT
    'docs-role-rl-' || u.username || '-' || g.n,
    k.id,
    m.id,
    CASE WHEN g.n % 2 = 0 THEN pc.id ELSE pl.id END,
    'success',
    now() - (g.n || ' seconds')::interval,
    now() - (g.n || ' seconds')::interval + interval '0.2 seconds',
    now() - (g.n || ' seconds')::interval + interval '0.3 seconds',
    now() - (g.n || ' seconds')::interval + interval '0.8 seconds',
    false, 0, u.id, k.team_id, 'docs-role-screenshots',
    true, true, 50000
FROM users u
JOIN api_keys k ON k.user_id = u.id AND k.name = 'docs-role-' || u.username || '-key'
CROSS JOIN generate_series(1, 3) AS g(n)
JOIN models m ON m.name = 'qwen-2.5-72b-instruct'
JOIN providers pc ON pc.name = 'Docs Cloud (EU)'
JOIN providers pl ON pl.name = 'Docs Local Worker'
WHERE u.username IN ('tobias.wasner', 'alexandra.szuminska', 'henriette.huhn');

-- Older mistral traffic so Model Management Last Used shows a dated row
-- (date + relative age), not only Never / Today.
INSERT INTO log_entry (
    request_id, api_key_id, model_id, provider_id, result_status,
    timestamp_request, timestamp_forwarding, time_at_first_token, timestamp_response,
    was_cold_start, queue_depth_at_enqueue, user_id, team_id, environment,
    rate_limit_admitted, cost_finalized, settled_cost_micro_cents
)
SELECT
    'docs-role-mistral-lu-' || g.n,
    k.id, m.id, p.id, 'success',
    now() - interval '2 days' - (g.n || ' hours')::interval,
    now() - interval '2 days' - (g.n || ' hours')::interval + interval '1 second',
    now() - interval '2 days' - (g.n || ' hours')::interval + interval '1.2 seconds',
    now() - interval '2 days' - (g.n || ' hours')::interval + interval '2 seconds',
    false, 0, k.user_id, k.team_id, 'docs-role-screenshots',
    true, true, 80000
FROM generate_series(1, 3) AS g(n)
JOIN api_keys k ON k.name = 'docs-role-tobias.wasner-key'
JOIN models m ON m.name = 'mistral-small-3.2-24b'
JOIN providers p ON p.name = 'Docs Cloud (EU)';

INSERT INTO usage_tokens (type_id, log_entry_id, token_count)
SELECT tt.id, le.id, 350 + (le.id % 200)
FROM log_entry le
JOIN token_types tt ON tt.name IN ('prompt_tokens', 'completion_tokens', 'billed_output_text')
WHERE le.environment = 'docs-role-screenshots'
  AND NOT EXISTS (
      SELECT 1 FROM usage_tokens ut
      WHERE ut.log_entry_id = le.id AND ut.type_id = tt.id
  );

-- Batches: one running, one finished.
INSERT INTO batch_objects (
    kind, upstream_id, execution, api_key_id, team_id, user_id, status,
    endpoint, total_requests, completed_requests, failed_requests,
    created_at, updated_at, started_at, finished_at, settled_at
)
SELECT
    'batch', 'batch_docs_in_progress', 'logos',
    k.id, k.team_id, k.user_id, 'in_progress',
    '/v1/chat/completions', 200, 137, 0,
    now() - interval '15 minutes', now(), now() - interval '14 minutes', NULL, NULL
FROM api_keys k
WHERE k.name = 'docs-role-tobias.wasner-key'
  AND NOT EXISTS (SELECT 1 FROM batch_objects WHERE upstream_id = 'batch_docs_in_progress');

INSERT INTO batch_objects (
    kind, upstream_id, execution, api_key_id, team_id, user_id, status,
    endpoint, total_requests, completed_requests, failed_requests,
    created_at, updated_at, started_at, finished_at, settled_at, output_file_id
)
SELECT
    'batch', 'batch_docs_completed', 'logos',
    k.id, k.team_id, k.user_id, 'completed',
    '/v1/chat/completions', 50, 50, 0,
    now() - interval '2 days', now() - interval '2 days',
    now() - interval '2 days', now() - interval '2 days' + interval '20 minutes',
    now() - interval '2 days' + interval '20 minutes',
    'file_docs_completed_out'
FROM api_keys k
WHERE k.name = 'docs-role-tobias.wasner-key'
  AND NOT EXISTS (SELECT 1 FROM batch_objects WHERE upstream_id = 'batch_docs_completed');

-- Agent sessions page content (no agent stack required).
INSERT INTO agent_workspaces (name, base_branch, volume_name, created_by)
SELECT v.name, 'main', 'docs-role-vol-' || v.suffix, 'docs-role-screenshots'
FROM (VALUES
    ('edutelligence from main', 'edu'),
    ('logos-ui from main', 'ui')
) AS v(name, suffix)
WHERE NOT EXISTS (SELECT 1 FROM agent_workspaces w WHERE w.name = v.name);

UPDATE agent_controls
SET mode = 'running',
    mode_reason = 'docs-role-screenshots',
    max_parallel = 4,
    updated_by = 'docs-role-screenshots',
    updated_at = now()
WHERE id = 1;

INSERT INTO agent_sessions (
    workspace_id, task, model, status,
    open_pull_request, created_by, created_at, started_at, finished_at,
    tokens_in, tokens_out, cost_usd
)
SELECT w.id, s.task, 'qwen-2.5-72b-instruct', s.status,
       true, 'docs-role-screenshots',
       now() - s.created_ago,
       CASE WHEN s.status = 'queued' THEN NULL ELSE now() - s.started_ago END,
       CASE WHEN s.status IN ('succeeded', 'failed') THEN now() - s.finished_ago ELSE NULL END,
       s.tin, s.tout, s.cost
FROM agent_workspaces w
JOIN (VALUES
    ('edutelligence from main', 'queued',
     'Investigate the statistics WebSocket reconnect loop on the requests tab',
     interval '10 minutes', interval '10 minutes', interval '0', 0, 0, 0::numeric),
    ('edutelligence from main', 'running',
     'Fix the flaky login spec in the e2e suite — it times out on slow runners',
     interval '2 hours', interval '1 hour 47 minutes', interval '0', 12000, 4000, 0.42),
    ('edutelligence from main', 'succeeded',
     'Add pagination to the request log export endpoint',
     interval '1 day', interval '1 day', interval '22 hours', 18000, 6000, 0.55),
    ('logos-ui from main', 'failed',
     'Remove the duplicated theme tokens from the data table component',
     interval '3 days', interval '3 days', interval '2 days 23 hours', 5000, 1200, 0.11)
) AS s(workspace_name, status, task, created_ago, started_ago, finished_ago, tin, tout, cost)
  ON s.workspace_name = w.name
WHERE NOT EXISTS (
    SELECT 1 FROM agent_sessions a
    WHERE a.created_by = 'docs-role-screenshots' AND a.task = s.task
);

COMMIT;

SELECT 'docs role-screenshots seed applied' AS status,
       (SELECT count(*) FROM models WHERE name IN (
            'llama-3.1-8b-instruct', 'qwen-2.5-72b-instruct', 'mistral-small-3.2-24b'
       )) AS models,
       (SELECT count(*) FROM policies WHERE name IN (
            'Local-first routing', 'Cost saver for drafts', 'High-quality answers'
       )) AS policies,
       (SELECT count(*) FROM log_entry WHERE environment = 'docs-role-screenshots') AS log_entries,
       (SELECT count(*) FROM batch_objects WHERE upstream_id LIKE 'batch_docs_%') AS batches,
       (SELECT count(*) FROM agent_sessions WHERE created_by = 'docs-role-screenshots') AS agent_sessions;
