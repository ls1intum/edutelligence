-- db/migrations/030_team_ownership.sql
ALTER TABLE team_members
    ADD COLUMN IF NOT EXISTS is_owner BOOLEAN NOT NULL DEFAULT false;

INSERT INTO schema_migrations (filename)
VALUES ('030_team_ownership.sql')
ON CONFLICT (filename) DO NOTHING;
