-- Requires psql variables: -v ollama_api_key='...'
BEGIN;

-- Force consistent Ollama provider URLs and auth headers
UPDATE providers
SET base_url = 'https://hochbruegge.aet.cit.tum.de/ollama',
    ollama_admin_url = 'https://hochbruegge.aet.cit.tum.de/ollama',
    auth_name = 'Authorization',
    auth_format = 'Bearer {}'
WHERE provider_type = 'ollama';

-- Ensure all Ollama model API keys use the shared key
UPDATE model_api_keys mak
SET api_key = :'ollama_api_key'
FROM providers p
WHERE p.id = mak.provider_id
  AND p.provider_type = 'ollama';

COMMIT;
