DO $$ BEGIN
    CREATE TYPE api_key_type_enum AS ENUM ('developer', 'application');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

ALTER TABLE teams
    ADD COLUMN IF NOT EXISTS default_cloud_rpm_limit INTEGER DEFAULT 5,
    ADD COLUMN IF NOT EXISTS default_cloud_tpm_limit INTEGER DEFAULT 10000,
    ADD COLUMN IF NOT EXISTS default_local_rpm_limit INTEGER DEFAULT 5,
    ADD COLUMN IF NOT EXISTS default_local_tpm_limit INTEGER DEFAULT 10000,
    ADD COLUMN IF NOT EXISTS default_monthly_budget_micro_cents BIGINT DEFAULT 100000000,
    ADD COLUMN IF NOT EXISTS team_monthly_budget_micro_cents BIGINT DEFAULT 500000000;

CREATE TABLE IF NOT EXISTS api_keys (
    id SERIAL PRIMARY KEY,
    key_value TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    key_type api_key_type_enum NOT NULL DEFAULT 'developer',
    team_id INTEGER REFERENCES teams(id) ON DELETE CASCADE,
    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    environment TEXT,
    log logging_enum DEFAULT 'BILLING',
    settings JSONB,
    default_priority INTEGER NOT NULL DEFAULT 1,
    is_active BOOLEAN NOT NULL DEFAULT true,
    legacy_process_id INTEGER REFERENCES process(id) ON DELETE SET NULL
);

UPDATE api_keys SET default_priority = 1 WHERE default_priority = 0;
CREATE INDEX IF NOT EXISTS idx_api_keys_team_id ON api_keys(team_id);
CREATE INDEX IF NOT EXISTS idx_api_keys_user_id ON api_keys(user_id);
CREATE INDEX IF NOT EXISTS idx_api_keys_active  ON api_keys(is_active) WHERE is_active = true;

INSERT INTO api_keys (key_value, name, key_type, team_id, user_id, environment, log, settings, is_active, legacy_process_id)
SELECT
    p.logos_key,
    p.name,
    CASE
        WHEN p.service_id IS NOT NULL THEN 'application'::api_key_type_enum
        ELSE 'developer'::api_key_type_enum
    END,
    (SELECT tm.team_id FROM team_members tm
     WHERE tm.user_id = p.user_id
     ORDER BY tm.team_id LIMIT 1),
    CASE WHEN p.service_id IS NOT NULL THEN NULL ELSE p.user_id END,
    CASE WHEN p.service_id IS NOT NULL THEN '-' ELSE NULL END,
    p.log,
    p.settings,
    true,
    p.id
FROM process p
ON CONFLICT (key_value) DO NOTHING;

CREATE TABLE IF NOT EXISTS team_model_permissions (
    team_id  INTEGER NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
    model_id INTEGER NOT NULL REFERENCES models(id) ON DELETE CASCADE,
    PRIMARY KEY (team_id, model_id)
);

CREATE TABLE IF NOT EXISTS api_key_model_permissions (
    api_key_id INTEGER NOT NULL REFERENCES api_keys(id) ON DELETE CASCADE,
    model_id   INTEGER NOT NULL REFERENCES models(id) ON DELETE CASCADE,
    PRIMARY KEY (api_key_id, model_id)
);

INSERT INTO api_key_model_permissions (api_key_id, model_id)
SELECT ak.id, pmp.model_id
FROM profile_model_permissions pmp
JOIN profiles pr ON pr.id = pmp.profile_id
JOIN api_keys ak ON ak.legacy_process_id = pr.process_id
ON CONFLICT DO NOTHING;

ALTER TABLE policies
    ADD COLUMN IF NOT EXISTS api_key_id INTEGER REFERENCES api_keys(id) ON DELETE CASCADE,
    ADD COLUMN IF NOT EXISTS team_id INTEGER REFERENCES teams(id) ON DELETE CASCADE;
ALTER TABLE policies ALTER COLUMN entity_id DROP NOT NULL;
ALTER TABLE policies ALTER COLUMN priority SET DEFAULT 5;
UPDATE policies SET priority = 5 WHERE priority = 0 OR priority IS NULL;

UPDATE policies p
SET api_key_id = ak.id, team_id = ak.team_id
FROM api_keys ak
WHERE ak.legacy_process_id = p.entity_id
AND   p.api_key_id IS NULL;

ALTER TABLE log_entry
    ADD COLUMN IF NOT EXISTS api_key_id INTEGER REFERENCES api_keys(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS team_id INTEGER REFERENCES teams(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS environment TEXT;

CREATE INDEX IF NOT EXISTS idx_log_entry_api_key_id ON log_entry(api_key_id);
CREATE INDEX IF NOT EXISTS idx_log_entry_team_id    ON log_entry(team_id);

UPDATE log_entry le
SET api_key_id = ak.id, team_id = ak.team_id, user_id = ak.user_id, environment = ak.environment
FROM api_keys ak
WHERE ak.legacy_process_id = le.process_id
AND   le.api_key_id IS NULL;

ALTER TABLE jobs
    ADD COLUMN IF NOT EXISTS api_key_id INTEGER REFERENCES api_keys(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS team_id INTEGER REFERENCES teams(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS environment TEXT;
ALTER TABLE jobs ALTER COLUMN process_id DROP NOT NULL;
ALTER TABLE jobs ALTER COLUMN profile_id DROP NOT NULL;
CREATE INDEX IF NOT EXISTS idx_jobs_api_key_id ON jobs(api_key_id);

UPDATE jobs j
SET api_key_id = ak.id, team_id = ak.team_id, user_id = ak.user_id, environment = ak.environment
FROM api_keys ak
WHERE ak.legacy_process_id = j.process_id
AND   j.api_key_id IS NULL;

CREATE TABLE IF NOT EXISTS budget_usage (
    api_key_id INTEGER NOT NULL REFERENCES api_keys(id) ON DELETE CASCADE,
    month DATE NOT NULL,
    cost_micro_cents BIGINT NOT NULL DEFAULT 0,
    PRIMARY KEY (api_key_id, month)
);
CREATE INDEX IF NOT EXISTS idx_budget_usage_month ON budget_usage(api_key_id, month);

INSERT INTO schema_migrations (filename)
VALUES ('031_restructure_api_keys_and_teams.sql')
ON CONFLICT (filename) DO NOTHING;