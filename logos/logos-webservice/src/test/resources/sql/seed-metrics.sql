INSERT INTO token_types (id, name) VALUES (9101, 'prompt_tokens'), (9102, 'completion_tokens');

INSERT INTO models (id, name, weight_latency, weight_accuracy, weight_cost, weight_quality, tags, description)
VALUES
  (5101, 'fast-model', 0, 0, 0, 0, 'metrics', 'Fast model'),
  (5102, 'slow-model', 0, 0, 0, 0, 'metrics', 'Slow model');

INSERT INTO providers (id, name, base_url, provider_type, cloud_provider_type, privacy_level, auth_name, auth_format, total_vram_mb)
VALUES
  (6101, 'cloud-provider', 'https://api.example.com', 'cloud', 'openai', 'LOCAL', 'Authorization', 'Bearer {}', NULL),
  (6102, 'local-provider', 'http://localhost:11434', 'logosnode', NULL, 'LOCAL', '', '', 8000);

INSERT INTO model_provider (id, provider_id, model_id)
VALUES (7101, 6101, 5101), (7102, 6102, 5101), (7103, 6101, 5102), (7104, 6102, 5102);

-- Cloud model prices (per-1K-token, micro-cents): fast 1000/2000, slow 4000/8000
INSERT INTO token_prices (id, type_id, model_id, provider_id, valid_from, price_per_k_token)
VALUES
  (92101, 9101, 5101, 6101, NOW() - INTERVAL '1 year', 1000),
  (92102, 9102, 5101, 6101, NOW() - INTERVAL '1 year', 2000),
  (92103, 9101, 5102, 6101, NOW() - INTERVAL '1 year', 4000),
  (92104, 9102, 5102, 6101, NOW() - INTERVAL '1 year', 8000);

-- 12 warm successful requests per pair, 10 completion tokens each
-- (5101, cloud): ttft 100ms, total 500ms; (5101, local): ttft 9000ms, total 40000ms
INSERT INTO log_entry (id, timestamp_request, timestamp_response, time_at_first_token, provider_id, model_id, result_status, was_cold_start)
SELECT 90000 + g, NOW() - (g || ' hours')::interval,
       NOW() - (g || ' hours')::interval + make_interval(secs => 0.5),
       NOW() - (g || ' hours')::interval + make_interval(secs => 0.1),
       6101, 5101, 'success', FALSE
FROM generate_series(1, 12) g;
INSERT INTO log_entry (id, timestamp_request, timestamp_response, time_at_first_token, provider_id, model_id, result_status, was_cold_start)
SELECT 90012 + g, NOW() - (g || ' hours')::interval,
       NOW() - (g || ' hours')::interval + make_interval(secs => 40),
       NOW() - (g || ' hours')::interval + make_interval(secs => 9),
       6102, 5101, 'success', FALSE
FROM generate_series(1, 12) g;
-- (5102, cloud): ttft 800ms, total 3000ms; (5102, local): ttft 200ms, total 900ms
INSERT INTO log_entry (id, timestamp_request, timestamp_response, time_at_first_token, provider_id, model_id, result_status, was_cold_start)
SELECT 90024 + g, NOW() - (g || ' hours')::interval,
       NOW() - (g || ' hours')::interval + make_interval(secs => 3),
       NOW() - (g || ' hours')::interval + make_interval(secs => 0.8),
       6101, 5102, 'success', FALSE
FROM generate_series(1, 12) g;
INSERT INTO log_entry (id, timestamp_request, timestamp_response, time_at_first_token, provider_id, model_id, result_status, was_cold_start)
SELECT 90036 + g, NOW() - (g || ' hours')::interval,
       NOW() - (g || ' hours')::interval + make_interval(secs => 0.9),
       NOW() - (g || ' hours')::interval + make_interval(secs => 0.2),
       6102, 5102, 'success', FALSE
FROM generate_series(1, 12) g;
-- cold start (excluded via was_cold_start), error (excluded via result_status),
-- and failed streaming: no first token, so excluded from the TTFT aggregate,
-- but still a total-latency sample (success with a response) - the metrics
-- test asserts 13 samples for the cloud pair on purpose.
INSERT INTO log_entry (id, timestamp_request, timestamp_response, time_at_first_token, provider_id, model_id, result_status, was_cold_start)
VALUES
  (90051, NOW(), NOW() + INTERVAL '60 seconds', NOW() + INTERVAL '30 seconds', 6101, 5101, 'success', TRUE),
  (90052, NOW(), NOW() + INTERVAL '60 seconds', NOW() + INTERVAL '30 seconds', 6101, 5101, 'error', FALSE),
  (90053, NOW(), NOW() + INTERVAL '60 seconds', NULL, 6101, 5101, 'success', FALSE);

INSERT INTO usage_tokens (type_id, log_entry_id, token_count)
SELECT 9102, id, 10 FROM log_entry WHERE id BETWEEN 90001 AND 90048;
