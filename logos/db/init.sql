-- Database: logos

GRANT ALL PRIVILEGES ON DATABASE logosdb TO postgres;
ALTER DATABASE logosdb OWNER TO postgres;

DROP TYPE IF EXISTS threshold_enum CASCADE;
DROP TABLE IF EXISTS profile_model_permissions CASCADE;
DROP TABLE IF EXISTS policies CASCADE;
DROP TABLE IF EXISTS model_api_keys CASCADE;
DROP TABLE IF EXISTS model_provider CASCADE;
DROP TABLE IF EXISTS models CASCADE;
DROP TABLE IF EXISTS providers CASCADE;
DROP TABLE IF EXISTS process CASCADE;
DROP TABLE IF EXISTS profiles CASCADE;
DROP TABLE IF EXISTS services CASCADE;
DROP TABLE IF EXISTS users CASCADE;
DROP TABLE IF EXISTS request_log CASCADE;
DROP TABLE IF EXISTS usage_log CASCADE;

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

CREATE TABLE profiles (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL
);

CREATE TABLE process (
    id SERIAL PRIMARY KEY,
    logos_key TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    service_id INTEGER REFERENCES services(id) ON DELETE CASCADE,
    profile_id INTEGER REFERENCES profiles(id) ON DELETE SET NULL,
    log BOOLEAN default(FALSE)
);

CREATE TABLE providers (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    base_url TEXT NOT NULL,
    auth_name TEXT NOT NULL,
    auth_format TEXT NOT NULL
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
    weight_quality INTEGER DEFAULT(0)
);

CREATE TABLE model_provider (
    id SERIAL PRIMARY KEY,
    provider_id INTEGER NOT NULL REFERENCES providers(id) ON DELETE CASCADE,
    model_id INTEGER NOT NULL REFERENCES models(id) ON DELETE CASCADE
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

CREATE TABLE request_log (
    id SERIAL PRIMARY KEY,
    timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    process_id INTEGER NOT NULL REFERENCES process(id) ON DELETE CASCADE,
    client_ip TEXT,
    input_payload JSONB,
    provider_id INTEGER,
    model_id INTEGER,
    headers JSONB
);

CREATE TABLE usage_log (
    id SERIAL PRIMARY KEY,
    request_id INTEGER NOT NULL REFERENCES request_log(id) ON DELETE CASCADE,
    timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    response_payload JSONB,
    prompt_tokens INTEGER,
    completion_tokens INTEGER,
    total_tokens INTEGER,
    provider_id INTEGER,
    model_id INTEGER
);
