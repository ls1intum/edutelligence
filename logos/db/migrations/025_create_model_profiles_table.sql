-- Migration: Create model_profiles table for calibrated VRAM profiles
-- Stores measured and estimated model resource profiles per provider.
-- Replaces reliance on JSONB-embedded profile data in runtime_payload.

CREATE TABLE IF NOT EXISTS model_profiles (
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

-- Fast lookups by provider (capacity planner queries all profiles for a provider)
CREATE INDEX IF NOT EXISTS idx_model_profiles_provider
    ON model_profiles(provider_id);

-- Find all profiles for a specific model across providers
CREATE INDEX IF NOT EXISTS idx_model_profiles_model_name
    ON model_profiles(model_name);

-- Filter by source to find models that still need measurement
CREATE INDEX IF NOT EXISTS idx_model_profiles_source
    ON model_profiles(residency_source)
    WHERE residency_source != 'measured';

COMMENT ON TABLE model_profiles IS
    'Calibrated model VRAM profiles per provider. base_residency_mb is derived from '
    'observed VRAM minus known KV cache budget after first load (residency_source=measured), '
    'or estimated from HuggingFace metadata / model name heuristic before first load.';

COMMENT ON COLUMN model_profiles.residency_source IS
    'Provenance of base_residency_mb: measured (observed - kv_sent), '
    'hf (HuggingFace safetensors), name (param count heuristic), '
    'override (operator config), cached (persisted from prior run)';
