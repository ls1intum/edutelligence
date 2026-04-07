-- Migration: Create schema_migrations table for tracking applied migrations
-- Idempotent: uses IF NOT EXISTS so it's safe to run multiple times
-- This table is used to track which migrations have been applied,
-- allowing the application to automatically apply pending migrations on startup.

CREATE TABLE IF NOT EXISTS schema_migrations (
    id SERIAL PRIMARY KEY,
    filename TEXT NOT NULL UNIQUE,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
