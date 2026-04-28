-- Migration: RBAC roles and teams
-- 1. Creates teams table to group users working on same application
-- 2. Creates team_members junction table
-- 3. Adds role and email columns to users
-- -> Everyone defaults to app_developer
-- -> Promote the initial Logos Admin:
--    UPDATE users SET role = 'logos_admin' WHERE id = <your_user_id>;

CREATE TABLE IF NOT EXISTS teams (
    id   SERIAL PRIMARY KEY,
    name TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS team_members (
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    team_id INTEGER NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
    PRIMARY KEY (user_id, team_id)
);

ALTER TABLE users
    ADD COLUMN IF NOT EXISTS role TEXT NOT NULL DEFAULT 'app_developer',
    ADD COLUMN IF NOT EXISTS email TEXT;

CREATE UNIQUE INDEX IF NOT EXISTS idx_users_email
ON users (lower(email))
WHERE email IS NOT NULL;

INSERT INTO schema_migrations (filename)
VALUES ('028_rbac_roles_and_teams.sql')
ON CONFLICT (filename) DO NOTHING;