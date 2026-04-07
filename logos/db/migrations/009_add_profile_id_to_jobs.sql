-- Migration: Add profile_id to jobs table for profile-level isolation
-- Safe to run multiple times; uses IF NOT EXISTS where supported.

-- Add profile_id column
ALTER TABLE jobs
    ADD COLUMN IF NOT EXISTS profile_id INTEGER REFERENCES profiles(id) ON DELETE CASCADE;

-- Backfill existing jobs with first available profile for their process
-- This is best-effort for legacy data
UPDATE jobs
SET profile_id = (
    SELECT id
    FROM profiles
    WHERE profiles.process_id = jobs.process_id
    ORDER BY id
    LIMIT 1
)
WHERE profile_id IS NULL;

-- Make profile_id NOT NULL (required going forward)
-- Note: This will fail if any jobs couldn't be backfilled
ALTER TABLE jobs
    ALTER COLUMN profile_id SET NOT NULL;
