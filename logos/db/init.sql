-- Database: logos

GRANT ALL PRIVILEGES ON DATABASE logosdb TO postgres;
ALTER DATABASE logosdb OWNER TO postgres;

DROP TYPE IF EXISTS threshold_enum CASCADE;
DROP TYPE IF EXISTS logging_enum CASCADE;
DROP TYPE IF EXISTS result_status_enum CASCADE;
DROP TABLE IF EXISTS profile_model_permissions CASCADE;
DROP TABLE IF EXISTS policies CASCADE;
DROP TABLE IF EXISTS model_api_keys CASCADE;
DROP TABLE IF EXISTS model_provider_config CASCADE;
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

CREATE TABLE users (
    id SERIAL PRIMARY KEY,
    username TEXT NOT NULL,
    prename TEXT,
    name TEXT
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
    provider_type VARCHAR(20) DEFAULT 'cloud',  -- 'ollama' or 'cloud'
    auth_name TEXT NOT NULL,
    auth_format TEXT NOT NULL,

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

CREATE TABLE model_api_keys (
    id SERIAL PRIMARY KEY,
    profile_id INTEGER REFERENCES profiles(id) ON DELETE CASCADE,
    provider_id INTEGER NOT NULL REFERENCES providers(id) ON DELETE CASCADE,
    api_key TEXT NOT NULL
);

CREATE TABLE models (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    endpoint TEXT NOT NULL,
    api_id INTEGER REFERENCES model_api_keys(id) ON DELETE SET NULL,
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

-- SDI: Per-model per-provider configuration for scheduling
-- Lookup chain: model_provider_config (here) → providers table → hardcoded defaults
CREATE TABLE model_provider_config (
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
    priority VARCHAR(10) DEFAULT 'medium',
    queue_depth_at_arrival INTEGER,
    utilization_at_arrival REAL,
    queue_wait_ms REAL,
    was_cold_start BOOLEAN DEFAULT FALSE,
    load_duration_ms REAL
);

CREATE TABLE token_types (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    description TEXT
);

CREATE TABLE usage_tokens (
    id SERIAL PRIMARY KEY,
    type_id INTEGER NOT NULL REFERENCES token_types(id) ON DELETE CASCADE,
    log_entry_id INTEGER NOT NULL REFERENCES log_entry(id) ON DELETE CASCADE,
    token_count INTEGER DEFAULT(0)
);

CREATE TABLE token_prices (
    id SERIAL PRIMARY KEY,
    type_id INTEGER NOT NULL REFERENCES token_types(id) ON DELETE CASCADE,
    valid_from TIMESTAMPTZ NOT NULL,
    price_per_k_token NUMERIC(10, 6) NOT NULL
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
