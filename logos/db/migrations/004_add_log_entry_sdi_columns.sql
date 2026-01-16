-- Migration: Add SDI scheduling and performance metrics to log_entry table
-- Safe to run multiple times; uses IF NOT EXISTS where supported.

-- Add scheduling priority
ALTER TABLE log_entry
    ADD COLUMN IF NOT EXISTS priority VARCHAR(10) DEFAULT 'medium';

-- Add queue metrics at arrival time
ALTER TABLE log_entry
    ADD COLUMN IF NOT EXISTS queue_depth_at_arrival INTEGER,
    ADD COLUMN IF NOT EXISTS utilization_at_arrival REAL;

-- Add performance metrics
ALTER TABLE log_entry
    ADD COLUMN IF NOT EXISTS queue_wait_ms REAL,
    ADD COLUMN IF NOT EXISTS was_cold_start BOOLEAN DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS load_duration_ms REAL;

-- Create indexes for common queries
CREATE INDEX IF NOT EXISTS idx_log_entry_priority ON log_entry(priority);
CREATE INDEX IF NOT EXISTS idx_log_entry_was_cold_start ON log_entry(was_cold_start);
CREATE INDEX IF NOT EXISTS idx_log_entry_model_provider ON log_entry(model_id, provider_id);
