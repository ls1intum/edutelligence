-- Two FULL-logging requests from team 2001 asking the same question, one
-- BILLING-only request that must not surface any question text at all (the
-- privacy gate is exactly what a test in seed-operations.sql alone cannot
-- exercise, since neither of its rows opts into FULL logging), and one
-- FULL-logging request using the Responses API's bare-string input shape
-- ({"input": "hello"}) rather than a chat/completions-style messages array.
INSERT INTO log_entry (id, request_id, api_key_id, model_id, provider_id, result_status,
                       timestamp_request, timestamp_forwarding, time_at_first_token, timestamp_response,
                       was_cold_start, queue_depth_at_enqueue, user_id, team_id, environment,
                       privacy_level, input_payload)
VALUES
  (9020, 'req-question-111', 3001, 5001, 6001, 'success',
   NOW() - INTERVAL '6 minutes', NOW() - INTERVAL '5 minutes',
   NOW() - INTERVAL '5 minutes 30 seconds', NOW() - INTERVAL '4 minutes',
   false, 1, 1001, 2001, NULL,
   'FULL', '{"model": "gpt-4o", "messages": [{"role": "user", "content": "What is the capital of France?"}]}'::jsonb),
  (9021, 'req-question-222', 3001, 5001, 6001, 'success',
   NOW() - INTERVAL '3 minutes', NOW() - INTERVAL '2 minutes',
   NOW() - INTERVAL '2 minutes 30 seconds', NOW() - INTERVAL '1 minute',
   false, 1, 1001, 2001, NULL,
   'FULL', '{"model": "gpt-4o", "messages": [{"role": "user", "content": "What is the capital of France?"}]}'::jsonb),
  (9022, 'req-question-333', 3001, 5001, 6001, 'success',
   NOW() - INTERVAL '2 minutes', NOW() - INTERVAL '1 minute',
   NOW() - INTERVAL '1 minute 30 seconds', NOW() - INTERVAL '30 seconds',
   false, 1, 1001, 2001, NULL,
   'BILLING', '{"model": "gpt-4o", "messages": [{"role": "user", "content": "This must never appear"}]}'::jsonb),
  (9023, 'req-question-444', 3001, 5001, 6001, 'success',
   NOW() - INTERVAL '1 minute', NOW() - INTERVAL '45 seconds',
   NOW() - INTERVAL '50 seconds', NOW() - INTERVAL '20 seconds',
   false, 1, 1001, 2001, NULL,
   'FULL', '{"model": "gpt-5", "input": "hello"}'::jsonb);
