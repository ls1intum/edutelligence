-- Migration: Rename provider name from openwebui to ollama and clear auth
-- Idempotent: only updates if the old value exists, safe to run multiple times

-- Rename provider from openwebui to ollama
UPDATE providers
SET name = 'ollama'
WHERE name = 'openwebui';

-- Clear auth for ollama provider (only if auth is currently set)
UPDATE providers
SET auth_name = '',
    auth_format = ''
WHERE name = 'ollama'
  AND (auth_name != '' OR auth_format != '');
