-- Migration 027: Dynamic logosnode deployments
--
-- For logosnode (worker-node) providers, models are announced dynamically via
-- WebSocket capabilities. This migration:
--
-- 1. Creates a logosnode_provider_keys table so workernode providers don't need
--    per-model entries in model_api_keys (they use a single shared key).
-- 2. Auto-syncing of model_provider rows is handled at the application layer
--    when capabilities are announced, so existing deployment queries continue
--    to work without schema changes.

-- Step 1: Create logosnode_provider_keys table
-- This replaces the need for per-model model_api_keys rows for logosnode providers.
-- Each logosnode provider has exactly one key (stored in providers.api_key already),
-- but this table makes the deployment query work without model_api_keys.
CREATE TABLE IF NOT EXISTS logosnode_provider_keys (
    id SERIAL PRIMARY KEY,
    provider_id INTEGER NOT NULL REFERENCES providers(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(provider_id)
);

-- Seed the table from existing logosnode providers
INSERT INTO logosnode_provider_keys (provider_id)
SELECT id FROM providers WHERE provider_type = 'logosnode'
ON CONFLICT (provider_id) DO NOTHING;

-- Record migration
INSERT INTO schema_migrations (filename)
VALUES ('027_logosnode_dynamic_deployments.sql')
ON CONFLICT (filename) DO NOTHING;
