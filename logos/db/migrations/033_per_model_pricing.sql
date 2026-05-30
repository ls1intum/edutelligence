DROP VIEW IF EXISTS budget_usage CASCADE;

DO $$ BEGIN
    CREATE TYPE cloud_provider_type_enum AS ENUM (
        'azure', 'openai', 'anthropic', 'gemini', 'bedrock', 'deepseek', 'groq'
    );
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

ALTER TABLE providers
    ADD COLUMN IF NOT EXISTS cloud_provider_type cloud_provider_type_enum DEFAULT NULL;

UPDATE providers
    SET provider_type = 'logosnode'
    WHERE LOWER(provider_type::text) IN ('ollama', 'node', 'node_controller', 'logos_worker_node');

UPDATE providers
    SET provider_type = 'cloud',
        cloud_provider_type = 'azure'
    WHERE LOWER(provider_type::text) = 'azure';

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_enum e
        JOIN pg_type t ON e.enumtypid = t.oid
        WHERE t.typname = 'provider_type_enum' AND e.enumlabel = 'azure'
    ) THEN
        CREATE TYPE provider_type_enum_v2 AS ENUM ('logosnode', 'cloud');
        ALTER TABLE providers ALTER COLUMN provider_type DROP DEFAULT;
        ALTER TABLE providers
            ALTER COLUMN provider_type TYPE provider_type_enum_v2
                USING provider_type::text::provider_type_enum_v2;
        ALTER TABLE providers ALTER COLUMN provider_type SET DEFAULT 'logosnode';
        DROP TYPE provider_type_enum;
        ALTER TYPE provider_type_enum_v2 RENAME TO provider_type_enum;
    ELSIF NOT EXISTS (
        SELECT 1 FROM pg_type WHERE typname = 'provider_type_enum'
    ) THEN
        CREATE TYPE provider_type_enum AS ENUM ('logosnode', 'cloud');
    END IF;
END $$;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'providers'
          AND column_name = 'provider_type'
          AND data_type = 'character varying'
    ) THEN
        ALTER TABLE providers ALTER COLUMN provider_type DROP DEFAULT;
        ALTER TABLE providers
            ALTER COLUMN provider_type TYPE provider_type_enum
                USING provider_type::provider_type_enum;
        ALTER TABLE providers ALTER COLUMN provider_type SET DEFAULT 'logosnode';
    END IF;
END $$;

ALTER TABLE providers
    ADD COLUMN IF NOT EXISTS privacy_level threshold_enum
        NOT NULL DEFAULT 'LOCAL';

UPDATE providers SET privacy_level = 'CLOUD_NOT_IN_EU_BY_US_PROVIDER'
    WHERE provider_type = 'cloud';

ALTER TABLE models DROP COLUMN IF EXISTS weight_privacy;

ALTER TABLE token_prices
    ADD COLUMN IF NOT EXISTS model_id INTEGER REFERENCES models(id) ON DELETE CASCADE;

ALTER TABLE token_prices
    ADD COLUMN IF NOT EXISTS provider_id INTEGER REFERENCES providers(id) ON DELETE CASCADE;

ALTER TABLE token_prices
    ALTER COLUMN price_per_k_token TYPE BIGINT USING ROUND(price_per_k_token)::BIGINT;

CREATE VIEW budget_usage AS
SELECT
    le.api_key_id,
    DATE_TRUNC('month', le.timestamp_request)::DATE AS month,
    COALESCE(SUM(
        CASE WHEN tp.price_per_k_token IS NOT NULL
             THEN (ut.token_count::BIGINT * tp.price_per_k_token / 1000)::BIGINT
             ELSE 0
        END
    ), 0) AS cost_micro_cents
FROM log_entry le
JOIN usage_tokens ut ON ut.log_entry_id = le.id
LEFT JOIN LATERAL (
    SELECT price_per_k_token
    FROM token_prices
    WHERE type_id = ut.type_id
      AND (model_id = le.model_id OR model_id IS NULL)
      AND (provider_id = le.provider_id OR provider_id IS NULL)
      AND valid_from <= le.timestamp_request
    ORDER BY (model_id    = le.model_id)    DESC NULLS LAST,
             (provider_id = le.provider_id) DESC NULLS LAST,
             valid_from DESC
    LIMIT 1
) tp ON true
WHERE le.api_key_id IS NOT NULL
GROUP BY le.api_key_id, DATE_TRUNC('month', le.timestamp_request)::DATE;
