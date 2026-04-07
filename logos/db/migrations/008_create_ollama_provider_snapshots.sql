-- Migration: Create ollama_provider_snapshots table for continuous Ollama provider monitoring
-- Safe to run multiple times; uses IF NOT EXISTS.
-- Tracks loaded models, VRAM usage, and resource metrics from /api/ps endpoint every 5 seconds

-- Create monitoring snapshots table (time-series data for Ollama providers)
CREATE TABLE IF NOT EXISTS ollama_provider_snapshots (
    id SERIAL PRIMARY KEY,
    ollama_admin_url TEXT NOT NULL,
    snapshot_ts TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    -- Aggregate metrics
    total_models_loaded INTEGER NOT NULL DEFAULT 0,
    total_vram_used_bytes BIGINT NOT NULL DEFAULT 0,

    -- Per-model details (JSONB array containing model name, size_vram, expires_at)
    loaded_models JSONB NOT NULL DEFAULT '[]'::jsonb,

    -- Error tracking
    poll_success BOOLEAN NOT NULL DEFAULT TRUE,
    error_message TEXT
);

-- Create indexes for efficient time-series queries
CREATE INDEX IF NOT EXISTS idx_provider_snapshots_url_ts
    ON ollama_provider_snapshots(ollama_admin_url, snapshot_ts DESC);

CREATE INDEX IF NOT EXISTS idx_provider_snapshots_ts
    ON ollama_provider_snapshots(snapshot_ts DESC);

CREATE INDEX IF NOT EXISTS idx_provider_snapshots_success
    ON ollama_provider_snapshots(poll_success)
    WHERE poll_success = FALSE;

CREATE INDEX IF NOT EXISTS idx_provider_snapshots_models
    ON ollama_provider_snapshots USING GIN (loaded_models);

-- Add table comment for documentation
COMMENT ON TABLE ollama_provider_snapshots IS
    'Time-series snapshots of Ollama provider state from /api/ps endpoint. Polled every 5 seconds for real-time monitoring.';
