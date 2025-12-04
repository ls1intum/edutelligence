-- Migration: add SSH connectivity columns for private Ollama providers
-- Safe to run multiple times; uses IF NOT EXISTS where supported.

ALTER TABLE providers
    ADD COLUMN IF NOT EXISTS ssh_host TEXT,
    ADD COLUMN IF NOT EXISTS ssh_user TEXT,
    ADD COLUMN IF NOT EXISTS ssh_port INTEGER DEFAULT 22,
    ADD COLUMN IF NOT EXISTS ssh_key_path TEXT,
    ADD COLUMN IF NOT EXISTS ssh_remote_ollama_port INTEGER DEFAULT 11434;
