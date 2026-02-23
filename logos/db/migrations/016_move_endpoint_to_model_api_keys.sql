-- Migration 016: Move endpoint from models to model_api_keys
--
-- The endpoint field is per-deployment (model+provider pair), not per-model.
-- Different providers can serve the same model at different endpoints.
-- Moving it to model_api_keys aligns with this relationship.
--
-- This migration:
-- 1. Adds endpoint column to model_api_keys
-- 2. Copies endpoint values from models (matched by model_id)
-- 3. Drops endpoint from models

BEGIN;

-- Step 1: Add endpoint column to model_api_keys
ALTER TABLE model_api_keys
    ADD COLUMN IF NOT EXISTS endpoint TEXT NOT NULL DEFAULT '';

-- Step 2: Copy endpoint values from models to matching model_api_keys rows
UPDATE model_api_keys mak
SET endpoint = m.endpoint
FROM models m
WHERE mak.model_id = m.id;

-- Step 3: Drop endpoint from models
ALTER TABLE models
    DROP COLUMN IF EXISTS endpoint;

COMMIT;
