-- Migration: Create model_provider_config table for SDI scheduling configuration
-- Safe to run multiple times; uses IF NOT EXISTS.

-- Create the table for per-model per-provider configuration
CREATE TABLE IF NOT EXISTS model_provider_config (
    model_id INTEGER NOT NULL REFERENCES models(id) ON DELETE CASCADE,
    provider_name VARCHAR(50) NOT NULL,

    -- SDI Configuration (per-model overrides)
    cold_start_threshold_ms REAL DEFAULT 1000.0,
    parallel_capacity INTEGER DEFAULT NULL,  -- NULL = use providers.parallel_capacity → default 1
    keep_alive_seconds INTEGER DEFAULT NULL,  -- NULL = use providers.keep_alive_seconds → default 300

    -- Observed statistics (auto-learned from actual requests)
    observed_avg_cold_load_ms REAL DEFAULT NULL,
    observed_avg_warm_load_ms REAL DEFAULT NULL,
    observed_cold_std_dev_ms REAL DEFAULT NULL,
    observed_warm_std_dev_ms REAL DEFAULT NULL,

    -- Counters for auto-learning
    cold_start_count INTEGER DEFAULT 0,
    warm_hit_count INTEGER DEFAULT 0,
    total_requests INTEGER DEFAULT 0,

    last_updated TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,

    PRIMARY KEY (model_id, provider_name)
);

-- Create index for faster lookups
CREATE INDEX IF NOT EXISTS idx_model_provider_config_model_id ON model_provider_config(model_id);
CREATE INDEX IF NOT EXISTS idx_model_provider_config_provider_name ON model_provider_config(provider_name);
