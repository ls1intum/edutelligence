-- Migration: Create request_events table and result_status_enum for SDI request monitoring
-- Safe to run multiple times; uses IF NOT EXISTS.

-- Create enum type for request result status
DO $$ BEGIN
    CREATE TYPE result_status_enum AS ENUM ('success', 'error', 'timeout');
EXCEPTION
    WHEN duplicate_object THEN null;
END $$;

-- Create request-level monitoring table (one row per request)
CREATE TABLE IF NOT EXISTS request_events (
    request_id TEXT PRIMARY KEY,
    model_id INTEGER REFERENCES models(id) ON DELETE SET NULL,
    provider_id INTEGER REFERENCES providers(id) ON DELETE SET NULL,

    -- Priority tracking
    initial_priority TEXT,
    priority_when_scheduled TEXT,

    -- Queue state tracking
    queue_depth_at_enqueue INTEGER,
    queue_depth_at_schedule INTEGER,

    -- Request configuration
    timeout_s INTEGER,

    -- Timestamps for lifecycle events
    enqueue_ts TIMESTAMPTZ,
    scheduled_ts TIMESTAMPTZ,
    request_complete_ts TIMESTAMPTZ,

    -- Resource availability at scheduling time
    available_vram_mb INTEGER,
    azure_rate_remaining_requests INTEGER,
    azure_rate_remaining_tokens INTEGER,

    -- Result tracking
    cold_start BOOLEAN,
    result_status result_status_enum,
    error_message TEXT
);

-- Create indexes for common query patterns
CREATE INDEX IF NOT EXISTS idx_request_events_model_id ON request_events(model_id);
CREATE INDEX IF NOT EXISTS idx_request_events_provider_id ON request_events(provider_id);
CREATE INDEX IF NOT EXISTS idx_request_events_result_status ON request_events(result_status);
CREATE INDEX IF NOT EXISTS idx_request_events_enqueue_ts ON request_events(enqueue_ts);
CREATE INDEX IF NOT EXISTS idx_request_events_cold_start ON request_events(cold_start);
CREATE INDEX IF NOT EXISTS idx_request_events_model_provider ON request_events(model_id, provider_id);
