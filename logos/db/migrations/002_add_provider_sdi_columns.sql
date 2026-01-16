-- Migration: Add SDI (Scheduling Data Interface) columns to providers table
-- Safe to run multiple times; uses IF NOT EXISTS where supported.

-- Add provider type distinction
ALTER TABLE providers
    ADD COLUMN IF NOT EXISTS provider_type VARCHAR(20) DEFAULT 'cloud';

-- Add Ollama-specific monitoring fields
ALTER TABLE providers
    ADD COLUMN IF NOT EXISTS ollama_admin_url TEXT DEFAULT '',
    ADD COLUMN IF NOT EXISTS total_vram_mb INTEGER DEFAULT NULL;

-- Add SDI configuration defaults
ALTER TABLE providers
    ADD COLUMN IF NOT EXISTS parallel_capacity INTEGER DEFAULT 1,
    ADD COLUMN IF NOT EXISTS keep_alive_seconds INTEGER DEFAULT 300,
    ADD COLUMN IF NOT EXISTS max_loaded_models INTEGER DEFAULT 3;

-- Add update tracking
ALTER TABLE providers
    ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP;

-- Update existing Ollama providers to have correct provider_type
UPDATE providers
SET provider_type = 'ollama'
WHERE LOWER(name) LIKE '%ollama%' OR LOWER(name) LIKE '%openwebui%';
