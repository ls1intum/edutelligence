INSERT INTO log_entry (id, request_id, api_key_id, model_id, provider_id, result_status,
                       timestamp_request, timestamp_forwarding, time_at_first_token, timestamp_response,
                       was_cold_start, queue_depth_at_enqueue, user_id, team_id, environment)
VALUES
  -- developer-key request: carries the requesting user and their team, no environment
  (9001, 'req-aaa-111', 3001, 5001, 6001, 'success',
   NOW() - INTERVAL '10 minutes', NOW() - INTERVAL '9 minutes',
   NOW() - INTERVAL '9 minutes 30 seconds', NOW() - INTERVAL '8 minutes',
   false, 1, 1001, 2001, NULL),
  -- application-key-style request: carries the environment, no user and no team
  (9002, 'req-bbb-222', 3001, 5001, 6001, 'success',
   NOW() - INTERVAL '5 minutes', NOW() - INTERVAL '4 minutes',
   NOW() - INTERVAL '4 minutes', NOW() - INTERVAL '3 minutes',
   true, 0, NULL, NULL, 'production');

INSERT INTO model_provider_benchmarks
  (id, model_provider_id, configuration, dataset, sample_size, metrics, recorded_at)
VALUES
  (8001, 7001,
   '{"tool":"guidellm","profile":{"kind":"synchronous"}}'::jsonb,
   'openai/gsm8k', 100,
   '{"request_rate":2.5,"request_latency_ms":{"p50":420.0,"p95":690.0}}'::jsonb,
   TIMESTAMPTZ '2026-08-24 12:00:00+00');

INSERT INTO ollama_provider_snapshots
  (id, provider_id, snapshot_ts, poll_success,
   total_vram_used_bytes, total_memory_bytes, free_memory_bytes,
   total_models_loaded, loaded_models, scheduler_signals)
VALUES
  (4001, 6001, NOW() - INTERVAL '1 minute', true,
   4294967296, 8589934592, 4294967296,
   1, '[]'::jsonb, '{}'::jsonb),
  -- fixed historical day for downsampling assertions: 4002+4003 share a minute,
  -- 4004 is in the next minute
  (4002, 6001, TIMESTAMPTZ '2024-06-01 10:00:05+00', true,
   1073741824, 8589934592, 7516192768,
   1, '[]'::jsonb, '{}'::jsonb),
  (4003, 6001, TIMESTAMPTZ '2024-06-01 10:00:25+00', true,
   2147483648, 8589934592, 6442450944,
   1, '[]'::jsonb, '{}'::jsonb),
  (4004, 6001, TIMESTAMPTZ '2024-06-01 10:01:10+00', true,
   3221225472, 8589934592, 5368709120,
   1, '[]'::jsonb, '{}'::jsonb);

INSERT INTO token_types (id, name) VALUES (91001, 'prompt_tokens') ON CONFLICT DO NOTHING;
INSERT INTO token_types (id, name) VALUES (91002, 'completion_tokens') ON CONFLICT DO NOTHING;

INSERT INTO usage_tokens (id, type_id, log_entry_id, token_count)
VALUES
  (93001, 91002, 9001, 4),
  (93002, 91002, 9002, 3);

-- The seeded usage above is completion_tokens (-> billed_output_text), so price
-- that dimension or log_entry_cost stays NULL and budget_usage reports 0. The
-- billed_input_uncached row backs the model-list price projection.
INSERT INTO token_prices (id, type_id, price_per_k_unit, valid_from, model_id)
SELECT 92001, tt.id, 1000, NOW() - INTERVAL '1 year', 5001
FROM token_types tt WHERE tt.name = 'billed_input_uncached';
INSERT INTO token_prices (id, type_id, price_per_k_unit, valid_from, model_id)
SELECT 92002, tt.id, 2000, NOW() - INTERVAL '1 year', 5001
FROM token_types tt WHERE tt.name = 'billed_output_text';
