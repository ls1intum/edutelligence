ALTER TABLE api_keys
ADD COLUMN IF NOT EXISTS use_custom_permissions BOOLEAN NOT NULL DEFAULT FALSE;

CREATE TABLE IF NOT EXISTS team_provider_permissions (
    team_id INTEGER NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
    provider_id INTEGER NOT NULL REFERENCES providers(id) ON DELETE CASCADE,
    PRIMARY KEY (team_id, provider_id)
);

CREATE TABLE IF NOT EXISTS api_key_provider_permissions (
    api_key_id INTEGER NOT NULL REFERENCES api_keys(id) ON DELETE CASCADE,
    provider_id INTEGER NOT NULL REFERENCES providers(id) ON DELETE CASCADE,
    PRIMARY KEY (api_key_id, provider_id)
);

CREATE INDEX IF NOT EXISTS idx_tpp_team_id ON team_provider_permissions(team_id);
CREATE INDEX IF NOT EXISTS idx_akpp_api_key_id ON api_key_provider_permissions(api_key_id);

INSERT INTO team_provider_permissions (team_id, provider_id)
SELECT t.id, p.id
FROM teams t
CROSS JOIN providers p
WHERE p.provider_type = 'logosnode'
ON CONFLICT (team_id, provider_id) DO NOTHING;

UPDATE api_keys
SET use_custom_permissions = TRUE
WHERE id IN (
    SELECT DISTINCT api_key_id FROM api_key_model_permissions
);

INSERT INTO api_key_model_permissions (api_key_id, model_id)
SELECT ak.id, tmp.model_id
FROM api_keys ak
JOIN team_model_permissions tmp ON ak.team_id = tmp.team_id
WHERE ak.use_custom_permissions = TRUE
ON CONFLICT DO NOTHING;

INSERT INTO api_key_provider_permissions (api_key_id, provider_id)
SELECT ak.id, p.id
FROM api_keys ak
CROSS JOIN providers p
WHERE ak.use_custom_permissions = TRUE
  AND p.provider_type = 'logosnode'
ON CONFLICT DO NOTHING;

DELETE FROM team_model_permissions
WHERE model_id NOT IN (
    SELECT DISTINCT mp.model_id
    FROM model_provider mp
    JOIN providers p ON p.id = mp.provider_id
    WHERE p.provider_type = 'logosnode'
);

DELETE FROM api_key_model_permissions
WHERE model_id NOT IN (
    SELECT DISTINCT mp.model_id
    FROM model_provider mp
    JOIN providers p ON p.id = mp.provider_id
    WHERE p.provider_type = 'logosnode'
);
