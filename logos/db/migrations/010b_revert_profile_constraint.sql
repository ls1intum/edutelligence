-- Migration 010b: Revert profile_id-based unique constraint
--
-- This reverts the constraint added in migration 010 to prepare for
-- restructuring model_api_keys to be model-based instead of profile-based.
--
-- Safe to run multiple times; uses IF EXISTS.

-- Drop the unique constraint on (profile_id, provider_id)
-- This constraint was added in migration 010 but is incorrect
-- API keys should be organized by model, not profile
ALTER TABLE model_api_keys
    DROP CONSTRAINT IF EXISTS model_api_keys_profile_provider_unique;

-- Verification query (run after migration):
-- SELECT conname FROM pg_constraint WHERE conname = 'model_api_keys_profile_provider_unique';
-- (should return 0 rows)
