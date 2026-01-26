BEGIN;

-- Deduplicate models by name (keep lowest id per name)
CREATE TEMP TABLE model_dupes AS
SELECT m.id AS old_id,
       mk.keep_id
FROM models m
JOIN (
    SELECT name, MIN(id) AS keep_id
    FROM models
    GROUP BY name
) mk ON m.name = mk.name
WHERE m.id <> mk.keep_id;

-- Re-map profile permissions to the kept model id
INSERT INTO profile_model_permissions (profile_id, model_id)
SELECT pmp.profile_id, md.keep_id
FROM profile_model_permissions pmp
JOIN model_dupes md ON pmp.model_id = md.old_id
WHERE NOT EXISTS (
    SELECT 1
    FROM profile_model_permissions p2
    WHERE p2.profile_id = pmp.profile_id
      AND p2.model_id = md.keep_id
);

DELETE FROM profile_model_permissions pmp
USING model_dupes md
WHERE pmp.model_id = md.old_id;

-- Update model references
UPDATE model_provider mp
SET model_id = md.keep_id
FROM model_dupes md
WHERE mp.model_id = md.old_id;

-- Deduplicate model_api_keys targets to avoid unique constraint violations after remap
CREATE TEMP TABLE mak_model_targets AS
SELECT mak.id,
       COALESCE(md.keep_id, mak.model_id) AS target_model_id,
       mak.provider_id
FROM model_api_keys mak
LEFT JOIN model_dupes md ON mak.model_id = md.old_id;

DELETE FROM model_api_keys mak
USING (
    SELECT id
    FROM (
        SELECT id,
               ROW_NUMBER() OVER (PARTITION BY target_model_id, provider_id ORDER BY id) AS rn
        FROM mak_model_targets
    ) t
    WHERE rn > 1
) dup
WHERE mak.id = dup.id;

UPDATE model_api_keys mak
SET model_id = md.keep_id
FROM model_dupes md
WHERE mak.model_id = md.old_id;

DELETE FROM model_provider_config mpc
USING model_dupes md
WHERE mpc.model_id = md.old_id
  AND EXISTS (
      SELECT 1
      FROM model_provider_config mpc2
      WHERE mpc2.model_id = md.keep_id
        AND mpc2.provider_name = mpc.provider_name
  );

UPDATE model_provider_config mpc
SET model_id = md.keep_id
FROM model_dupes md
WHERE mpc.model_id = md.old_id;

UPDATE log_entry le
SET model_id = md.keep_id
FROM model_dupes md
WHERE le.model_id = md.old_id;

UPDATE request_events re
SET model_id = md.keep_id
FROM model_dupes md
WHERE re.model_id = md.old_id;

-- Remove duplicate model_provider rows
DELETE FROM model_provider mp
USING model_provider mp2
WHERE mp.id > mp2.id
  AND mp.model_id = mp2.model_id
  AND mp.provider_id = mp2.provider_id;

DELETE FROM models m
USING model_dupes md
WHERE m.id = md.old_id;

-- Deduplicate providers by base_url (keep lowest id per base_url)
CREATE TEMP TABLE provider_dupes AS
SELECT p.id AS old_id,
       pk.keep_id
FROM providers p
JOIN (
    SELECT base_url, MIN(id) AS keep_id
    FROM providers
    GROUP BY base_url
) pk ON p.base_url = pk.base_url
WHERE p.id <> pk.keep_id;

-- Deduplicate model_api_keys targets to avoid unique constraint violations after provider remap
CREATE TEMP TABLE mak_provider_targets AS
SELECT mak.id,
       mak.model_id,
       COALESCE(pd.keep_id, mak.provider_id) AS target_provider_id
FROM model_api_keys mak
LEFT JOIN provider_dupes pd ON mak.provider_id = pd.old_id;

DELETE FROM model_api_keys mak
USING (
    SELECT id
    FROM (
        SELECT id,
               ROW_NUMBER() OVER (PARTITION BY model_id, target_provider_id ORDER BY id) AS rn
        FROM mak_provider_targets
    ) t
    WHERE rn > 1
) dup
WHERE mak.id = dup.id;

UPDATE model_api_keys mak
SET provider_id = pd.keep_id
FROM provider_dupes pd
WHERE mak.provider_id = pd.old_id;

-- model_provider_config references provider_name (not provider_id), so no provider remap needed

UPDATE model_provider mp
SET provider_id = pd.keep_id
FROM provider_dupes pd
WHERE mp.provider_id = pd.old_id;

DELETE FROM model_provider mp
USING model_provider mp2
WHERE mp.id > mp2.id
  AND mp.model_id = mp2.model_id
  AND mp.provider_id = mp2.provider_id;

UPDATE log_entry le
SET provider_id = pd.keep_id
FROM provider_dupes pd
WHERE le.provider_id = pd.old_id;

UPDATE request_events re
SET provider_id = pd.keep_id
FROM provider_dupes pd
WHERE re.provider_id = pd.old_id;

DELETE FROM providers p
USING provider_dupes pd
WHERE p.id = pd.old_id;

COMMIT;
