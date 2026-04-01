-- Migration: extend ollama_provider_snapshots with worker-runtime memory fields
-- Required so persisted LogosWorkerNode history can reconstruct used/free/total
-- memory over time instead of guessing capacity from peak usage.

ALTER TABLE ollama_provider_snapshots
  ADD COLUMN IF NOT EXISTS total_memory_bytes BIGINT,
  ADD COLUMN IF NOT EXISTS free_memory_bytes BIGINT,
  ADD COLUMN IF NOT EXISTS snapshot_source TEXT;

UPDATE ollama_provider_snapshots s
SET
  total_memory_bytes = COALESCE(
    s.total_memory_bytes,
    CASE
      WHEN p.total_vram_mb IS NOT NULL AND p.total_vram_mb > 0
        THEN (p.total_vram_mb::bigint * 1024 * 1024)
      ELSE NULL
    END
  ),
  free_memory_bytes = COALESCE(
    s.free_memory_bytes,
    CASE
      WHEN p.total_vram_mb IS NOT NULL AND p.total_vram_mb > 0
        THEN GREATEST((p.total_vram_mb::bigint * 1024 * 1024) - s.total_vram_used_bytes, 0)
      ELSE NULL
    END
  ),
  snapshot_source = COALESCE(s.snapshot_source, 'legacy')
FROM providers p
WHERE p.id = s.provider_id;

UPDATE ollama_provider_snapshots
SET snapshot_source = COALESCE(snapshot_source, 'legacy');
