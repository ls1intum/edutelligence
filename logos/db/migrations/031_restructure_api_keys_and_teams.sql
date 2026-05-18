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

WITH users_without_team AS (
    SELECT u.id, u.username
    FROM users u
    WHERE u.username IS NOT NULL
      AND u.username <> 'root'
      AND NOT EXISTS (
          SELECT 1
          FROM team_members tm
          WHERE tm.user_id = u.id
      )
      AND EXISTS (
          SELECT 1 FROM process p
          WHERE p.user_id = u.id AND p.service_id IS NULL
      )
      AND NOT EXISTS (
          SELECT 1 FROM process p
          WHERE p.user_id = u.id AND p.service_id IS NOT NULL
      )
)
INSERT INTO teams (name)
SELECT uwt.username
FROM users_without_team uwt
WHERE NOT EXISTS (
    SELECT 1
    FROM teams t
    WHERE t.name = uwt.username
);

WITH service_teams AS (
    SELECT DISTINCT s.name AS team_name
    FROM services s
    WHERE s.name IS NOT NULL
)
INSERT INTO teams (name)
SELECT st.team_name
FROM service_teams st
WHERE NOT EXISTS (
    SELECT 1
    FROM teams t
    WHERE t.name = st.team_name
);

WITH users_without_team AS (
    SELECT u.id, u.username
    FROM users u
    WHERE u.username IS NOT NULL
      AND u.username <> 'root'
      AND NOT EXISTS (
          SELECT 1
          FROM team_members tm
          WHERE tm.user_id = u.id
      )
      AND EXISTS (
          SELECT 1 FROM process p
          WHERE p.user_id = u.id AND p.service_id IS NULL
      )
      AND NOT EXISTS (
          SELECT 1 FROM process p
          WHERE p.user_id = u.id AND p.service_id IS NOT NULL
      )
)
INSERT INTO team_members (user_id, team_id)
SELECT uwt.id, t.id
FROM users_without_team uwt
JOIN LATERAL (
    SELECT id
    FROM teams
    WHERE name = uwt.username
    ORDER BY id
    LIMIT 1
) t ON true;

WITH application_process_members AS (
    SELECT DISTINCT
        p.user_id,
        t.id AS team_id
    FROM process p
    JOIN services s ON s.id = p.service_id
    JOIN teams t ON t.name = s.name
    JOIN users u ON u.id = p.user_id
    WHERE p.service_id IS NOT NULL
      AND p.user_id IS NOT NULL
      AND u.username <> 'root'
)
INSERT INTO team_members (user_id, team_id)
SELECT apm.user_id, apm.team_id
FROM application_process_members apm
WHERE NOT EXISTS (
    SELECT 1
    FROM team_members tm
    WHERE tm.user_id = apm.user_id
      AND tm.team_id = apm.team_id
);

UPDATE team_members tm
SET is_owner = true
FROM users u
WHERE tm.user_id = u.id
  AND u.username <> 'root'
  AND tm.team_id = (SELECT t.id FROM teams t WHERE t.name = u.username ORDER BY t.id LIMIT 1)
  AND EXISTS (
      SELECT 1 FROM process p
      WHERE p.user_id = u.id
        AND p.service_id IS NULL
  );

UPDATE team_members tm
SET is_owner = true
FROM users u
JOIN process p ON p.user_id = u.id AND p.service_id IS NOT NULL
JOIN services s ON s.id = p.service_id
JOIN teams t ON t.name = s.name
WHERE tm.user_id = u.id
  AND tm.team_id = t.id
  AND u.username <> 'root';

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
CREATE INDEX IF NOT EXISTS idx_api_keys_active ON api_keys(is_active) WHERE is_active = true;

WITH process_owner AS (
    SELECT
        p.*,
        COALESCE(
            (
                SELECT u.id
                FROM users u
                WHERE u.id = p.user_id
                LIMIT 1
            ),
            (
                SELECT u.id
                FROM users u
                WHERE u.username = p.name
                ORDER BY u.id
                LIMIT 1
            )
        ) AS owner_user_id,
        s.name AS service_team_name
    FROM process p
    LEFT JOIN services s ON s.id = p.service_id
),
process_with_team AS (
    SELECT
        po.*,
        (
            SELECT tm.team_id
            FROM team_members tm
            WHERE tm.user_id = po.owner_user_id
            ORDER BY tm.team_id
            LIMIT 1
        ) AS owner_team_id,
        (
            SELECT t.id
            FROM teams t
            WHERE t.name = po.service_team_name
            ORDER BY t.id
            LIMIT 1
        ) AS service_team_id,
        EXISTS (
            SELECT 1
            FROM users root_user
            WHERE root_user.username = 'root'
              AND root_user.id = po.owner_user_id
        ) AS is_root_owner
    FROM process_owner po
)
INSERT INTO api_keys (key_value, name, key_type, team_id, user_id, environment, log, settings, is_active, legacy_process_id)
SELECT
    pwt.logos_key,
    pwt.name,
    CASE
        WHEN pwt.service_id IS NOT NULL THEN 'application'::api_key_type_enum
        ELSE 'developer'::api_key_type_enum
    END,
    CASE
        WHEN pwt.service_id IS NOT NULL THEN pwt.service_team_id
        WHEN pwt.is_root_owner THEN NULL
        ELSE pwt.owner_team_id
    END,
    CASE
        WHEN pwt.service_id IS NOT NULL THEN NULL
        ELSE pwt.owner_user_id
    END,
    CASE
        WHEN pwt.service_id IS NOT NULL THEN COALESCE(substring(pwt.name from '-(prod|test|staging|dev)$'), '-')
        ELSE NULL
    END,
    pwt.log,
    pwt.settings,
    true,
    pwt.id
FROM process_with_team pwt
ON CONFLICT (key_value) DO UPDATE SET
    name = EXCLUDED.name,
    key_type = EXCLUDED.key_type,
    team_id = EXCLUDED.team_id,
    user_id = EXCLUDED.user_id,
    environment = EXCLUDED.environment,
    log = EXCLUDED.log,
    settings = EXCLUDED.settings,
    is_active = EXCLUDED.is_active,
    legacy_process_id = EXCLUDED.legacy_process_id;

CREATE EXTENSION IF NOT EXISTS pgcrypto;

INSERT INTO api_keys (key_value, name, key_type, team_id, user_id, environment, log, settings, is_active)
SELECT DISTINCT ON (u.id, t.id)
    'lg-' ||
    left(trim(both '-' from regexp_replace(lower(t.name || '-' || u.username), '[^a-z0-9-]+', '-', 'g')), 35) ||
    '-' || translate(replace(encode(gen_random_bytes(72), 'base64'), E'\n', ''), '+/=', '-_'),
    u.username || '-' || t.name || '-dev-key',
    'developer'::api_key_type_enum,
    t.id,
    u.id,
    NULL,
    'BILLING'::logging_enum,
    NULL::jsonb,
    true
FROM process p
JOIN users u ON u.id = p.user_id
JOIN services s ON s.id = p.service_id
JOIN teams t ON t.name = s.name
WHERE p.service_id IS NOT NULL
  AND p.user_id IS NOT NULL
  AND u.username <> 'root'
  AND NOT EXISTS (
      SELECT 1 FROM api_keys ak
      WHERE ak.user_id = u.id AND ak.team_id = t.id AND ak.key_type = 'developer'
  )
ORDER BY u.id, t.id;

CREATE UNIQUE INDEX IF NOT EXISTS idx_api_keys_legacy_process_id_unique
    ON api_keys(legacy_process_id)
    WHERE legacy_process_id IS NOT NULL;

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

CREATE INDEX IF NOT EXISTS idx_log_entry_process_id ON log_entry(process_id);
CREATE INDEX IF NOT EXISTS idx_log_entry_api_key_id ON log_entry(api_key_id);
CREATE INDEX IF NOT EXISTS idx_log_entry_team_id ON log_entry(team_id);

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

WITH legacy_service_only_users AS (
    SELECT u.id
    FROM users u
    WHERE u.username <> 'root'
      AND NOT EXISTS (
          SELECT 1
          FROM process p
          WHERE p.user_id = u.id
            AND p.service_id IS NULL
      )
      AND NOT EXISTS (
          SELECT 1
          FROM api_keys ak
          WHERE ak.user_id = u.id
            AND (
                ak.legacy_process_id IS NULL
                OR EXISTS (
                    SELECT 1 FROM process p
                    WHERE p.id = ak.legacy_process_id
                      AND p.user_id = u.id
                )
            )
      )
)
DELETE FROM team_members tm
USING legacy_service_only_users lsu
WHERE tm.user_id = lsu.id;

WITH legacy_service_only_users AS (
    SELECT u.id
    FROM users u
    WHERE u.username <> 'root'
      AND NOT EXISTS (
          SELECT 1
          FROM process p
          WHERE p.user_id = u.id
            AND p.service_id IS NULL
      )
      AND NOT EXISTS (
          SELECT 1
          FROM api_keys ak
          WHERE ak.user_id = u.id
            AND (
                ak.legacy_process_id IS NULL
                OR EXISTS (
                    SELECT 1 FROM process p
                    WHERE p.id = ak.legacy_process_id
                      AND p.user_id = u.id
                )
            )
      )
)
DELETE FROM users u
USING legacy_service_only_users lsu
WHERE u.id = lsu.id;

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