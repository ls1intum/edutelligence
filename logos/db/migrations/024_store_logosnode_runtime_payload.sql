-- Migration: persist rich LogosWorkerNode runtime payloads and derived scheduler signals
-- Keeps the existing memory chart fields, but also stores the full worker runtime snapshot
-- and compact scheduler-facing metrics for vLLM/Ollama-backed local providers.

ALTER TABLE ollama_provider_snapshots
  ADD COLUMN IF NOT EXISTS runtime_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
  ADD COLUMN IF NOT EXISTS scheduler_signals JSONB NOT NULL DEFAULT '{}'::jsonb;

UPDATE ollama_provider_snapshots
SET
  runtime_payload = COALESCE(runtime_payload, '{}'::jsonb),
  scheduler_signals = COALESCE(scheduler_signals, '{}'::jsonb);
