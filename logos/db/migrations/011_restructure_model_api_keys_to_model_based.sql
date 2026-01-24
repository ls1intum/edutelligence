-- Migration 011: Restructure model_api_keys from profile-based to model-based
--
-- Background:
-- The model_api_keys table incorrectly uses (profile_id, provider_id) as the key.
-- API keys should be tied to models, not profiles, since:
-- 1. Models are served by providers (linked via model_provider table)
-- 2. API keys are infrastructure-level credentials for accessing providers
-- 3. All profiles should share the same API key for a given model-provider pair
--
-- This migration:
-- 1. Creates a new table with model_id instead of profile_id
-- 2. Populates it from model_provider table + existing API keys
-- 3. Replaces the old table with the new one
--
-- Safe to run multiple times; checks if already applied.

-- Step 1: Check if restructuring is already complete
DO $$
BEGIN
    -- If model_id column already exists and profile_id doesn't, migration is done
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'model_api_keys' AND column_name = 'model_id'
    ) AND NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'model_api_keys' AND column_name = 'profile_id'
    ) THEN
        RAISE NOTICE 'Migration 011 already applied (model_id exists, profile_id does not). Skipping.';
        RETURN;
    END IF;

    -- Step 2: Create new table with model-based structure
    RAISE NOTICE 'Creating model_api_keys_new table...';
    CREATE TABLE IF NOT EXISTS model_api_keys_new (
        id SERIAL PRIMARY KEY,
        model_id INTEGER NOT NULL REFERENCES models(id) ON DELETE CASCADE,
        provider_id INTEGER NOT NULL REFERENCES providers(id) ON DELETE CASCADE,
        api_key TEXT NOT NULL,
        UNIQUE(model_id, provider_id)
    );

    -- Step 3: Populate from model_provider + existing API keys
    RAISE NOTICE 'Populating model_api_keys_new from model_provider and existing keys...';
    INSERT INTO model_api_keys_new (model_id, provider_id, api_key)
    SELECT DISTINCT
        mp.model_id,
        mp.provider_id,
        COALESCE(
            (SELECT api_key FROM model_api_keys WHERE provider_id = mp.provider_id AND api_key != '' LIMIT 1),
            ''  -- Default empty key if none found
        ) as api_key
    FROM model_provider mp
    ON CONFLICT (model_id, provider_id) DO NOTHING;

    -- Step 4: Report on missing keys
    RAISE NOTICE 'Checking for entries with empty API keys...';
    PERFORM model_id, provider_id FROM model_api_keys_new WHERE api_key = '';
    IF FOUND THEN
        RAISE WARNING 'Some model-provider pairs have empty API keys. These should be updated manually.';
    END IF;

    -- Step 5: Drop old table and rename new one
    RAISE NOTICE 'Replacing old table with new structure...';
    DROP TABLE IF EXISTS model_api_keys CASCADE;
    ALTER TABLE model_api_keys_new RENAME TO model_api_keys;

    RAISE NOTICE 'Migration 011 completed successfully!';
END $$;

-- Verification queries (run these after migration to verify):
--
-- 1. Check that model_api_keys has model_id, not profile_id:
--    \d model_api_keys
--
-- 2. Verify row count matches model_provider:
--    SELECT COUNT(*) FROM model_api_keys;
--    SELECT COUNT(*) FROM model_provider;
--    (should be equal)
--
-- 3. Verify unique constraint exists:
--    SELECT conname FROM pg_constraint WHERE conname = 'model_api_keys_model_id_provider_id_key';
--    (should return 1 row)
--
-- 4. Check for empty API keys that need manual updates:
--    SELECT * FROM model_api_keys WHERE api_key = '';
