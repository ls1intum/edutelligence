INSERT INTO models (id, name, weight_latency, weight_accuracy, weight_cost, weight_quality, tags, parallel, description)
VALUES (5001, 'gpt-4',   0, 10, -5,  8,  'cloud,gpt', 1, 'GPT-4 model');

INSERT INTO models (id, name, weight_latency, weight_accuracy, weight_cost, weight_quality, tags, parallel, description)
VALUES (5002, 'gpt-3.5', -10, 0, 10, -5, 'cloud,gpt', 1, 'GPT-3.5 model');

INSERT INTO providers (id, name, base_url, provider_type, privacy_level, auth_name, auth_format)
VALUES (6001, 'openai-provider', 'https://api.openai.com', 'cloud', 'LOCAL', 'Authorization', 'Bearer {}');

INSERT INTO model_provider (id, provider_id, model_id, endpoint, api_key)
VALUES (7001, 6001, 5001, NULL, NULL);