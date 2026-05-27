-- Migration 032: Remove legacy structure
DROP TABLE IF EXISTS profile_model_permissions CASCADE;
DROP TABLE IF EXISTS profiles CASCADE;
DROP TABLE IF EXISTS process CASCADE;
DROP TABLE IF EXISTS services CASCADE;

ALTER TABLE policies DROP COLUMN IF EXISTS entity_id;

ALTER TABLE log_entry DROP COLUMN IF EXISTS process_id;

ALTER TABLE jobs DROP COLUMN IF EXISTS process_id;
ALTER TABLE jobs DROP COLUMN IF EXISTS profile_id;

ALTER TABLE api_keys DROP COLUMN IF EXISTS legacy_process_id;

INSERT INTO schema_migrations (filename)
VALUES ('032_remove_legacy_structure.sql')
ON CONFLICT (filename) DO NOTHING;