-- Migration: Replace ollama_admin_url with provider_id FK in ollama_provider_snapshots
-- This enables proper relational lookups and allows the UI to display provider names.

-- 1. Add provider_id column (nullable first for backfill)
ALTER TABLE ollama_provider_snapshots
  ADD COLUMN IF NOT EXISTS provider_id INTEGER;

-- 2. Backfill from providers table using URL match
UPDATE ollama_provider_snapshots s
SET provider_id = p.id
FROM providers p
WHERE p.ollama_admin_url = s.ollama_admin_url;

-- 3. Delete orphaned rows (URLs with no matching provider)
DELETE FROM ollama_provider_snapshots WHERE provider_id IS NULL;

-- 4. Set NOT NULL constraint
ALTER TABLE ollama_provider_snapshots
  ALTER COLUMN provider_id SET NOT NULL;

-- 5. Add foreign key constraint
ALTER TABLE ollama_provider_snapshots
  ADD CONSTRAINT fk_snapshots_provider
  FOREIGN KEY (provider_id) REFERENCES providers(id) ON DELETE CASCADE;

-- 6. Drop old column and replace index
DROP INDEX IF EXISTS idx_provider_snapshots_url_ts;
ALTER TABLE ollama_provider_snapshots DROP COLUMN IF EXISTS ollama_admin_url;
CREATE INDEX IF NOT EXISTS idx_provider_snapshots_provider_ts
  ON ollama_provider_snapshots(provider_id, snapshot_ts DESC);
