-- Migration 032: Convert users.role from TEXT to a real ENUM type.
--
-- Migration 028 added `role TEXT NOT NULL DEFAULT 'app_developer'` but did
-- NOT carry over the CHECK constraint from db/init.sql, so existing
-- deployments could end up with empty or otherwise invalid values. Empty
-- strings pass NOT NULL but break the UI: the `data.role as UserRole` cast
-- in auth-shell.tsx silently lies, then `HOME_ROUTE[role]` is undefined and
-- the page hangs on the loading spinner.
--
-- This migration makes invalid values impossible at the DB level by
-- promoting the column to a real ENUM type.

-- 1) Backfill any pre-existing bad values to the default.
UPDATE users
SET role = 'app_developer'
WHERE role IS NULL
   OR role NOT IN ('app_developer', 'app_admin', 'logos_admin');

-- 2) Drop the legacy CHECK constraint if it exists (only present on
--    deployments created from db/init.sql; absent on those that came up
--    purely via migrations).
ALTER TABLE users DROP CONSTRAINT IF EXISTS users_role_check;

-- 3) Create the ENUM type if it doesn't already exist.
DO $$ BEGIN
    CREATE TYPE user_role AS ENUM ('app_developer', 'app_admin', 'logos_admin');
EXCEPTION WHEN duplicate_object THEN
    NULL;
END $$;

-- 4) Convert the column. PostgreSQL refuses to alter a column type while a
--    DEFAULT of the old type is set, so drop and re-set the default.
ALTER TABLE users ALTER COLUMN role DROP DEFAULT;
ALTER TABLE users ALTER COLUMN role TYPE user_role USING role::user_role;
ALTER TABLE users ALTER COLUMN role SET DEFAULT 'app_developer'::user_role;

INSERT INTO schema_migrations (filename)
VALUES ('032_users_role_enum.sql')
ON CONFLICT (filename) DO NOTHING;
