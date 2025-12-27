-- Migration: Rename provider name from openwebui to ollama and clear auth
-- Idempotent: re-running leaves values unchanged once updated.

UPDATE providers
SET name = 'ollama'
WHERE name = 'openwebui';

UPDATE providers
SET auth_name = '',
    auth_format = ''
WHERE name = 'ollama';
