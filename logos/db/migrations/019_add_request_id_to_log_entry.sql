-- Migration: Add request_id column to log_entry for direct join with request_events

ALTER TABLE log_entry
    ADD COLUMN IF NOT EXISTS request_id TEXT;

CREATE INDEX IF NOT EXISTS idx_log_entry_request_id ON log_entry(request_id);
