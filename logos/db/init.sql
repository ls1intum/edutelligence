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
DROP TABLE IF EXISTS request_events CASCADE;

CREATE TABLE users (
    id SERIAL PRIMARY KEY,
    username TEXT NOT NULL,
    prename TEXT,
    name TEXT,
    email TEXT
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_users_email ON users(email);

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

    -- SDI: Scheduling and performance metrics
    request_id TEXT,  -- Links to request_events for scheduler metrics
    priority VARCHAR(10) DEFAULT 'medium',
    queue_depth_at_arrival INTEGER,
    utilization_at_arrival REAL,
    queue_wait_ms REAL,
    was_cold_start BOOLEAN DEFAULT FALSE,
    load_duration_ms REAL
);

CREATE INDEX idx_log_entry_request_id ON log_entry(request_id);

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

-- Request-level monitoring (one row per request)
CREATE TABLE request_events (
    request_id TEXT PRIMARY KEY,
    model_id INTEGER REFERENCES models(id) ON DELETE SET NULL,
    provider_id INTEGER REFERENCES providers(id) ON DELETE SET NULL,

    initial_priority TEXT,
    priority_when_scheduled TEXT,

    queue_depth_at_enqueue INTEGER,
    queue_depth_at_schedule INTEGER,

    timeout_s INTEGER,

    enqueue_ts TIMESTAMPTZ,
    scheduled_ts TIMESTAMPTZ,
    request_complete_ts TIMESTAMPTZ,

    available_vram_mb INTEGER,
    azure_rate_remaining_requests INTEGER,
    azure_rate_remaining_tokens INTEGER,

    cold_start BOOLEAN,
    result_status result_status_enum,
    error_message TEXT
);
