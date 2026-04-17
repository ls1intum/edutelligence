-- Database: logos

GRANT ALL PRIVILEGES ON DATABASE logosdb TO postgres;
ALTER DATABASE logosdb OWNER TO postgres;

DROP TYPE IF EXISTS threshold_enum CASCADE;
DROP TYPE IF EXISTS logging_enum CASCADE;
DROP TYPE IF EXISTS result_status_enum CASCADE;
DROP TYPE IF EXISTS job_status_enum CASCADE;
DROP TABLE IF EXISTS profile_model_permissions CASCADE;
DROP TABLE IF EXISTS policies CASCADE;
DROP TABLE IF EXISTS model_api_keys CASCADE;
DROP TABLE IF EXISTS provider_config CASCADE;
DROP TABLE IF EXISTS model_provider CASCADE;
DROP TABLE IF EXISTS models CASCADE;
DROP TABLE IF EXISTS providers CASCADE;
DROP TABLE IF EXISTS process CASCADE;
DROP TABLE IF EXISTS profiles CASCADE;
DROP TABLE IF EXISTS services CASCADE;
DROP TABLE IF EXISTS users CASCADE;
DROP TABLE IF EXISTS log_entry CASCADE;
DROP TABLE IF EXISTS token_types CASCADE;
DROP TABLE IF EXISTS usage_tokens CASCADE;
DROP TABLE IF EXISTS token_prices CASCADE;
DROP TABLE IF EXISTS jobs CASCADE;
DROP TABLE IF EXISTS ollama_provider_snapshots CASCADE;
DROP TABLE IF EXISTS model_profiles CASCADE;
DROP TABLE IF EXISTS logosnode_provider_keys CASCADE;
DROP TABLE IF EXISTS schema_migrations CASCADE;
DROP TABLE IF EXISTS team_members CASCADE;
DROP TABLE IF EXISTS teams CASCADE;

CREATE TABLE users (
    id SERIAL PRIMARY KEY,
    username TEXT NOT NULL,
    prename TEXT,
    name TEXT,
    role TEXT NOT NULL DEFAULT 'app_developer'
        CHECK (role IN ('app_developer', 'app_admin', 'logos_admin')),
    email TEXT
);

CREATE UNIQUE INDEX idx_users_email
ON users (lower(email))
WHERE email IS NOT NULL;

CREATE TABLE teams (
    id   SERIAL PRIMARY KEY,
    name TEXT NOT NULL
);

CREATE TABLE team_members (
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    team_id INTEGER NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
    PRIMARY KEY (user_id, team_id)
);

CREATE TABLE services (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL
);

CREATE TYPE logging_enum as ENUM ('BILLING', 'FULL');
CREATE TYPE result_status_enum as ENUM ('success', 'error', 'timeout');

CREATE TABLE process (
    id SERIAL PRIMARY KEY,
    logos_key TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    service_id INTEGER REFERENCES services(id) ON DELETE CASCADE,
    log logging_enum DEFAULT('BILLING'),
    settings JSONB
);

CREATE TABLE profiles (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    process_id INTEGER REFERENCES process(id) ON DELETE SET NULL
);

CREATE TABLE providers (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    base_url TEXT NOT NULL,
    provider_type VARCHAR(20) DEFAULT 'cloud',  -- e.g., 'ollama' or 'azure'
    auth_name TEXT NOT NULL,
    auth_format TEXT NOT NULL,
    api_key TEXT DEFAULT NULL,

    -- SDI: Ollama-specific monitoring fields (NULL for cloud providers)
    ollama_admin_url TEXT DEFAULT '',  -- TODO: For Ollama providers, add internal admin endpoint when avaliable
    total_vram_mb INTEGER DEFAULT NULL,  -- Total VRAM capacity (e.g., 49152 for 48GB)



    -- SDI: Configuration defaults for this provider
    parallel_capacity INTEGER DEFAULT 1,
    keep_alive_seconds INTEGER DEFAULT 300,
    max_loaded_models INTEGER DEFAULT 3,

    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE TYPE threshold_enum as ENUM ('LOCAL', 'CLOUD_IN_EU_BY_US_PROVIDER', 'CLOUD_NOT_IN_EU_BY_US_PROVIDER', 'CLOUD_IN_EU_BY_EU_PROVIDER');

CREATE TABLE models (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    weight_privacy threshold_enum DEFAULT('LOCAL'),
    weight_latency INTEGER DEFAULT(0),
    weight_accuracy INTEGER DEFAULT(0),
    weight_cost INTEGER DEFAULT(0),
    weight_quality INTEGER DEFAULT(0),
    tags TEXT,
    parallel INTEGER DEFAULT(1) CONSTRAINT minimum CHECK (parallel BETWEEN 1 and 256),
    description TEXT
);

CREATE TABLE model_provider (
    id SERIAL PRIMARY KEY,
    provider_id INTEGER NOT NULL REFERENCES providers(id) ON DELETE CASCADE,
    model_id INTEGER NOT NULL REFERENCES models(id) ON DELETE CASCADE
);

CREATE TABLE model_api_keys (
    id SERIAL PRIMARY KEY,
    model_id INTEGER NOT NULL REFERENCES models(id) ON DELETE CASCADE,
    provider_id INTEGER NOT NULL REFERENCES providers(id) ON DELETE CASCADE,
    api_key TEXT NOT NULL,
    endpoint TEXT NOT NULL DEFAULT '',
    UNIQUE(model_id, provider_id)
);

-- Per-provider key for logosnode workers (replaces per-model model_api_keys for workers)
CREATE TABLE logosnode_provider_keys (
    id SERIAL PRIMARY KEY,
    provider_id INTEGER NOT NULL REFERENCES providers(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(provider_id)
);

CREATE TABLE profile_model_permissions (
    id SERIAL PRIMARY KEY,
    profile_id INTEGER REFERENCES profiles(id) ON DELETE CASCADE,
    model_id INTEGER NOT NULL REFERENCES models(id) ON DELETE CASCADE
);

CREATE TABLE policies (
    id SERIAL PRIMARY KEY,
    entity_id INTEGER NOT NULL REFERENCES process(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    description TEXT,
    threshold_privacy threshold_enum DEFAULT('LOCAL'),
    threshold_latency INTEGER DEFAULT(0),
    threshold_accuracy INTEGER DEFAULT(0),
    threshold_cost INTEGER DEFAULT(0),
    threshold_quality INTEGER DEFAULT(0),
    priority INTEGER DEFAULT(0),
    topic TEXT
);

CREATE TABLE log_entry (
    id SERIAL PRIMARY KEY,
    timestamp_request TIMESTAMPTZ NOT NULL,
    timestamp_forwarding TIMESTAMPTZ,
    timestamp_response TIMESTAMPTZ,
    time_at_first_token TIMESTAMPTZ,
    privacy_level logging_enum DEFAULT('BILLING'),

    process_id INTEGER REFERENCES process(id) ON DELETE SET NULL,

    client_ip TEXT,
    input_payload JSONB,
    headers JSONB,

    response_payload JSONB,
    provider_id INTEGER REFERENCES providers(id) ON DELETE SET NULL,
    model_id INTEGER REFERENCES models(id) ON DELETE SET NULL,
    policy_id INTEGER REFERENCES policies(id) ON DELETE SET NULL,
    classification_statistics JSONB,

    -- Request lifecycle and performance metrics
    request_id TEXT,
    priority VARCHAR(10) DEFAULT 'medium',
    initial_priority TEXT,
    priority_when_scheduled TEXT,
    queue_depth_at_enqueue INTEGER,
    queue_depth_at_schedule INTEGER,
    timeout_s INTEGER,
    queue_depth_at_arrival INTEGER,
    utilization_at_arrival REAL,
    queue_wait_ms REAL,
    was_cold_start BOOLEAN DEFAULT FALSE,
    load_duration_ms REAL,
    available_vram_mb INTEGER,
    azure_rate_remaining_requests INTEGER,
    azure_rate_remaining_tokens INTEGER,
    result_status result_status_enum,
    error_message TEXT
);

CREATE INDEX idx_log_entry_request_id ON log_entry(request_id);
CREATE UNIQUE INDEX idx_log_entry_request_id_unique ON log_entry(request_id) WHERE request_id IS NOT NULL;

CREATE TABLE token_types (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    description TEXT
);

CREATE TABLE usage_tokens (
    id SERIAL PRIMARY KEY,
    type_id INTEGER NOT NULL REFERENCES token_types(id) ON DELETE CASCADE,
    log_entry_id INTEGER NOT NULL REFERENCES log_entry(id) ON DELETE CASCADE,
    token_count BIGINT DEFAULT(0)
);

CREATE TABLE token_prices (
    id SERIAL PRIMARY KEY,
    type_id INTEGER NOT NULL REFERENCES token_types(id) ON DELETE CASCADE,
    valid_from TIMESTAMPTZ NOT NULL,
    price_per_k_token NUMERIC(10, 6) NOT NULL
);

CREATE TYPE job_status_enum as ENUM ('pending', 'running', 'success', 'failed');

-- Job status table (made for polling the status for long-running tasks)
CREATE TABLE jobs (
    id SERIAL PRIMARY KEY,
    status job_status_enum NOT NULL DEFAULT 'pending',
    process_id INTEGER NOT NULL REFERENCES process(id) ON DELETE CASCADE,
    profile_id INTEGER NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    request_payload JSONB NOT NULL,
    result_payload JSONB,
    error_message TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Time-series snapshots of Ollama provider state from /api/ps endpoint
CREATE TABLE ollama_provider_snapshots (
    id SERIAL PRIMARY KEY,
    provider_id INTEGER NOT NULL REFERENCES providers(id) ON DELETE CASCADE,
    snapshot_ts TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    -- Aggregate metrics
    total_models_loaded INTEGER NOT NULL DEFAULT 0,
    total_vram_used_bytes BIGINT NOT NULL DEFAULT 0,

    -- Per-model details (JSONB array containing model name, size_vram, expires_at)
    loaded_models JSONB NOT NULL DEFAULT '[]'::jsonb,

    -- Error tracking
    poll_success BOOLEAN NOT NULL DEFAULT TRUE,
    error_message TEXT,

    -- Worker runtime memory fields (from migration 023)
    total_memory_bytes BIGINT,
    free_memory_bytes BIGINT,
    snapshot_source TEXT,

    -- Rich runtime payloads and scheduler signals (from migration 024)
    runtime_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    scheduler_signals JSONB NOT NULL DEFAULT '{}'::jsonb
);

-- Create indexes for efficient time-series queries
CREATE INDEX idx_provider_snapshots_provider_ts
    ON ollama_provider_snapshots(provider_id, snapshot_ts DESC);
CREATE INDEX idx_provider_snapshots_ts
    ON ollama_provider_snapshots(snapshot_ts DESC);
CREATE INDEX idx_provider_snapshots_success
    ON ollama_provider_snapshots(poll_success)
    WHERE poll_success = FALSE;
CREATE INDEX idx_provider_snapshots_models
    ON ollama_provider_snapshots USING GIN (loaded_models);

-- Calibrated model VRAM profiles per provider
CREATE TABLE model_profiles (
    id SERIAL PRIMARY KEY,
    provider_id INTEGER NOT NULL REFERENCES providers(id) ON DELETE CASCADE,
    model_name TEXT NOT NULL,

    -- VRAM measurements
    base_residency_mb REAL,            -- model weights + runtime overhead (MB)
    loaded_vram_mb REAL,               -- total observed VRAM when loaded (weights + KV)
    sleeping_residual_mb REAL,         -- VRAM while sleeping (L1/L2)
    kv_budget_mb REAL,                 -- KV cache allocation (MB)

    -- Model metadata
    disk_size_bytes BIGINT,            -- on-disk weight size (bytes)
    engine TEXT,                        -- 'vllm' or 'ollama'
    tensor_parallel_size INTEGER,
    kv_per_token_bytes INTEGER,        -- KV cache bytes per token (from architecture)
    max_context_length INTEGER,

    -- Calibration provenance
    residency_source TEXT,             -- 'measured', 'hf', 'name', 'override', 'cached'
    measurement_count INTEGER NOT NULL DEFAULT 0,
    last_measured_at TIMESTAMPTZ,

    -- GPU utilization bounds
    observed_gpu_memory_utilization REAL,
    min_gpu_memory_utilization_to_load REAL,

    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    UNIQUE(provider_id, model_name)
);

-- Fast lookups by provider
CREATE INDEX idx_model_profiles_provider
    ON model_profiles(provider_id);

-- Find all profiles for a specific model across providers
CREATE INDEX idx_model_profiles_model_name
    ON model_profiles(model_name);

-- Filter by source to find models that still need measurement
CREATE INDEX idx_model_profiles_source
    ON model_profiles(residency_source)
    WHERE residency_source != 'measured';

-- Track applied migrations
CREATE TABLE schema_migrations (
    id SERIAL PRIMARY KEY,
    filename TEXT NOT NULL UNIQUE,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
