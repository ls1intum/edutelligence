ALTER TABLE model_provider
    ADD COLUMN IF NOT EXISTS api_key TEXT DEFAULT NULL,
    ADD COLUMN IF NOT EXISTS endpoint TEXT DEFAULT NULL;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM information_schema.tables
        WHERE table_schema = 'public' AND table_name = 'model_api_keys'
    ) THEN
        EXECUTE '
            INSERT INTO model_provider (model_id, provider_id)
            SELECT mak.model_id, mak.provider_id
            FROM model_api_keys mak
            WHERE NOT EXISTS (
                SELECT 1
                FROM model_provider mp
                WHERE mak.model_id = mp.model_id
                AND mak.provider_id = mp.provider_id
            );
        ';

        EXECUTE '
            UPDATE model_provider mp
            SET api_key = mak.api_key,
                endpoint = mak.endpoint
            FROM model_api_keys mak
            WHERE mak.model_id = mp.model_id
                AND mak.provider_id = mp.provider_id;
        ';
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'uq_model_provider_mapping'
    ) THEN
        ALTER TABLE model_provider
        ADD CONSTRAINT uq_model_provider_mapping UNIQUE(model_id, provider_id);
    END IF;
END $$;

DROP TABLE IF EXISTS model_api_keys CASCADE;
