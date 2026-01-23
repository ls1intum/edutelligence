-- Migration: Remove api_id column from models table
--
-- Background:
-- The api_id column in models table is redundant and creates incorrect binding.
-- API keys should be looked up via (profile_id, provider_id) from model_api_keys,
-- not via a direct foreign key in the models table.
--
-- The runtime code already uses the correct lookup pattern via:
-- model_id -> provider_id (from model_provider) -> (profile_id, provider_id) -> api_key
--
-- This migration:
-- 1. Adds UNIQUE constraint to model_api_keys(profile_id, provider_id)
-- 2. Drops the api_id column from models table
--
-- Safe to run multiple times; uses IF EXISTS/IF NOT EXISTS where supported.

-- Step 1: Add unique constraint to enforce one API key per profile per provider
-- This ensures data integrity in the new model
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'model_api_keys_profile_provider_unique'
    ) THEN
        -- Before adding constraint, deduplicate any existing violations
        -- Keep the most recently updated key for each (profile_id, provider_id)
        DELETE FROM model_api_keys a
        USING model_api_keys b
        WHERE a.id < b.id
          AND a.profile_id = b.profile_id
          AND a.provider_id = b.provider_id;

        -- Now add the constraint
        ALTER TABLE model_api_keys
            ADD CONSTRAINT model_api_keys_profile_provider_unique
            UNIQUE (profile_id, provider_id);
    END IF;
END $$;

-- Step 2: Drop the api_id foreign key column from models table
-- This is safe because the runtime code uses get_key_to_model_provider()
-- which looks up keys via (profile_id, provider_id) instead
ALTER TABLE models
    DROP COLUMN IF EXISTS api_id;

-- Verification queries (run these after migration to verify):
--
-- 1. Check that model_api_keys has unique (profile_id, provider_id):
--    SELECT profile_id, provider_id, COUNT(*)
--    FROM model_api_keys
--    GROUP BY profile_id, provider_id
--    HAVING COUNT(*) > 1;
--    (should return 0 rows)
--
-- 2. Verify models table no longer has api_id:
--    SELECT column_name FROM information_schema.columns
--    WHERE table_name = 'models' AND column_name = 'api_id';
--    (should return 0 rows)
