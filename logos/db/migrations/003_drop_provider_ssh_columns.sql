-- Migration: drop SSH connectivity columns for private Ollama providers
-- Safe to run; uses IF EXISTS.

ALTER TABLE providers
    DROP COLUMN IF EXISTS ssh_host,
    DROP COLUMN IF EXISTS ssh_user,
    DROP COLUMN IF EXISTS ssh_port,
    DROP COLUMN IF EXISTS ssh_key_path,
    DROP COLUMN IF EXISTS ssh_remote_ollama_port;
