-- Migration 014: Add email column to users table for iPraktikum support
-- This enables batch user provisioning and CSV export features

ALTER TABLE users ADD COLUMN IF NOT EXISTS email TEXT;
CREATE UNIQUE INDEX IF NOT EXISTS idx_users_email ON users(email);
