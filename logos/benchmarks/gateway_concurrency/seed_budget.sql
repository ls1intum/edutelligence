-- Seed data for the budget-admission leg of the gateway benchmark.
-- Run AFTER seed.sql (it reuses that file's team, model and provider):
--   psql "$LOGOS_DB_URL" -v bench_budget_rows=200000 -f seed_budget.sql
--
-- seed.sql leaves every budget NULL on purpose, so the concurrency ramp
-- measures the executor pool and nothing else. That also means the budget
-- check never runs in those legs, and log_entry stays empty. A budget
-- refresh that re-prices a key's whole month is free on an empty table and
-- expensive on a production-sized one, so neither of those legs can see it.
-- This seed builds the case they miss: an application key WITH a budget
-- limit, and a month of history behind it.
--
-- Variables (psql -v):
--   bench_budget_rows         (200000) history rows for the budget key
--   bench_budget_unfinalized  (50)     percent of those rows left unpriced
--                                      (cost_finalized = FALSE), the shape
--                                      direct-cloud rows had before the
--                                      gateway stored their price at settle
--
-- The limit is far above anything the run can spend: the leg measures how
-- long admission takes, not what a 402 looks like.
--
-- Idempotent: deletes its own rows first (key 502 and its log rows).

\set ON_ERROR_STOP on

\if :{?bench_budget_rows}
\else
\set bench_budget_rows 200000
\endif
\if :{?bench_budget_unfinalized}
\else
\set bench_budget_unfinalized 50
\endif

BEGIN;

-- ---------------------------------------------------------------------------
-- Clean up a previous budget seed. usage_tokens cascade with log_entry.
-- ---------------------------------------------------------------------------
DELETE FROM log_entry WHERE api_key_id = 502;
DELETE FROM api_key_provider_permissions WHERE api_key_id = 502;
DELETE FROM api_key_model_permissions    WHERE api_key_id = 502;
DELETE FROM api_keys WHERE id = 502;
DELETE FROM token_prices WHERE model_id = 501 AND provider_id = 501;

-- ---------------------------------------------------------------------------
-- Application key with a key budget limit. An application key with a limit
-- is exactly the shape whose admission sums the key's month of spend
-- (GatewayBudgetService.apiKeyBudgetUsage). Rate limits stay unset.
-- ---------------------------------------------------------------------------
INSERT INTO api_keys (
    id, key_value, name, key_type, team_id, user_id, environment, log,
    settings, default_priority, is_active, use_custom_permissions
)
VALUES (
    502, 'lg-bench-gw-budget-0000', 'bench-gw-budget-key', 'application', 501, NULL, 'test', 'BILLING',
    '{"budget_limit_micro_cents": 1000000000000000}'::jsonb, 1, true, false
);

-- ---------------------------------------------------------------------------
-- Prices, so the history rows price to a real figure through
-- logos_price_usage instead of short-circuiting to NULL.
-- ---------------------------------------------------------------------------
INSERT INTO token_types (name, description) VALUES
    ('prompt_tokens', ''), ('completion_tokens', '')
ON CONFLICT (name) DO NOTHING;

INSERT INTO token_prices (type_id, model_id, provider_id, unit, min_context_tokens, service_tier, valid_from, price_per_k_unit)
SELECT tt.id, 501, 501, 'token', 0, 'default', '2020-01-01T00:00:00Z'::timestamptz, p.price
FROM (VALUES ('billed_input_uncached', 20000), ('billed_output_text', 120000)) AS p(name, price)
JOIN token_types tt ON tt.name = p.name;

-- ---------------------------------------------------------------------------
-- A month of successful direct-cloud history for the key, spread evenly
-- from the start of the current month to now. request_id carries the gw-
-- prefix the gateway uses, so the rows match every gateway-only predicate
-- (including the partial indexes the gateway relies on).
-- ---------------------------------------------------------------------------
INSERT INTO log_entry (
    timestamp_request, timestamp_forwarding, timestamp_response,
    api_key_id, team_id, environment, model_id, provider_id, request_id,
    result_status, cost_finalized, settled_cost_micro_cents, privacy_level
)
SELECT
    ts, ts, ts + INTERVAL '800 milliseconds',
    502, 501, 'test', 501, 501, 'gw-bench-budget-' || g,
    'success',
    (g % 100) >= :bench_budget_unfinalized,
    CASE WHEN (g % 100) >= :bench_budget_unfinalized THEN 56000 ELSE NULL END,
    'BILLING'
FROM generate_series(1, :bench_budget_rows) AS g
CROSS JOIN LATERAL (
    SELECT date_trunc('month', NOW())
           + (NOW() - date_trunc('month', NOW())) * (g::double precision / :bench_budget_rows) AS ts
) AS t;

-- Token counts for every history row. Finalized rows never read them on the
-- budget path; unfinalized rows are re-priced from them on every read.
INSERT INTO usage_tokens (log_entry_id, type_id, token_count)
SELECT le.id, tt.id, CASE tt.name WHEN 'prompt_tokens' THEN 1000 ELSE 300 END
FROM log_entry le
CROSS JOIN token_types tt
WHERE le.api_key_id = 502
  AND tt.name IN ('prompt_tokens', 'completion_tokens');

SELECT setval('api_keys_id_seq', GREATEST(502, (SELECT last_value FROM api_keys_id_seq)));

COMMIT;

ANALYZE log_entry;
ANALYZE usage_tokens;

SELECT COUNT(*) AS budget_rows,
       COUNT(*) FILTER (WHERE NOT cost_finalized) AS unfinalized_rows
FROM log_entry WHERE api_key_id = 502;
