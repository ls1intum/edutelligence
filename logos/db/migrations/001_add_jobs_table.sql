-- Add jobs table for async job tracking
CREATE TYPE IF NOT EXISTS job_status_enum AS ENUM ('pending', 'running', 'success', 'failed');

CREATE TABLE IF NOT EXISTS jobs (
    id SERIAL PRIMARY KEY,
    status job_status_enum NOT NULL DEFAULT 'pending',
    request_payload JSONB NOT NULL,
    result_payload JSONB,
    error_message TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
