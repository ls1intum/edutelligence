-- Migration: bump default provider parallel_capacity 1 → 20
--
-- Rationale: vLLM uses continuous batching, so the legacy default of 1 is
-- far too conservative; 20 matches the new workernode LaneConfig default
-- and keeps DB-default rows consistent with what workers actually report.
--
-- Existing rows pinned at the legacy default (1) are bumped to 20 so they
-- pick up the new behavior; rows with any other explicit value are left
-- untouched. Idempotent: re-running is a no-op.

ALTER TABLE providers
    ALTER COLUMN parallel_capacity SET DEFAULT 20;

UPDATE providers
SET parallel_capacity = 20
WHERE parallel_capacity = 1;
