-- ROLLBACK for Migration 010: Remove api_id column from models table
--
-- WARNING: This rollback will restore the api_id column but all previous
-- api_id values will be lost (set to NULL). You should only run this if
-- you need to revert the migration immediately after running it.
--
-- If you've already deployed code changes that don't use api_id, DO NOT
-- run this rollback as it will cause inconsistencies.

-- Step 1: Restore the api_id column to models table
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'models' AND column_name = 'api_id'
    ) THEN
        ALTER TABLE models
            ADD COLUMN api_id INTEGER REFERENCES model_api_keys(id) ON DELETE SET NULL;
    END IF;
END $$;

-- Step 2: Remove the unique constraint from model_api_keys
-- Note: This allows duplicate (profile_id, provider_id) pairs again
ALTER TABLE model_api_keys
    DROP CONSTRAINT IF EXISTS model_api_keys_profile_provider_unique;

-- Step 3: Verification
-- Check that api_id column exists in models table:
--   SELECT column_name FROM information_schema.columns
--   WHERE table_name = 'models' AND column_name = 'api_id';
--   (should return 1 row)
--
-- Check that unique constraint is removed:
--   SELECT conname FROM pg_constraint
--   WHERE conname = 'model_api_keys_profile_provider_unique';
--   (should return 0 rows)

-- WARNING: After rollback, you must also revert all code changes from
-- 010_CODE_CHANGES_REQUIRED.md or the application will malfunction.
