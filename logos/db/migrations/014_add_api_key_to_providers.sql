-- Migration: Add api_key column to providers table
-- Moves the API key from model_api_keys (per model/provider pair) to providers (per provider)

BEGIN;

-- Add the new column
ALTER TABLE providers ADD COLUMN IF NOT EXISTS api_key TEXT DEFAULT NULL;

-- Prefill from model_api_keys: pick the first api_key per provider (lowest model_api_keys.id)
UPDATE providers p
SET api_key = sub.api_key
FROM (
    SELECT DISTINCT ON (provider_id) provider_id, api_key
    FROM model_api_keys
    ORDER BY provider_id, id
) sub
WHERE p.id = sub.provider_id;

COMMIT;
