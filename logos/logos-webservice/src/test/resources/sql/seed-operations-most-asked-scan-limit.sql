-- Three FULL-logging requests from team 2001, each asking a different
-- question, staggered so the scan-limit test can tell them apart: the digest
-- is built from the newest consented rows of the window, so with a scan limit
-- of two (set by the test) the oldest question must fall out of it. The base
-- seed's rows are BILLING-only and do not count against the limit.
INSERT INTO log_entry (id, request_id, api_key_id, model_id, provider_id, result_status,
                       timestamp_request, timestamp_forwarding, time_at_first_token, timestamp_response,
                       was_cold_start, queue_depth_at_enqueue, user_id, team_id, environment,
                       privacy_level, input_payload)
VALUES
  (9050, 'req-scan-050', 3001, 5001, 6001, 'success',
   NOW() - INTERVAL '9 minutes', NOW() - INTERVAL '8 minutes',
   NOW() - INTERVAL '8 minutes 30 seconds', NOW() - INTERVAL '7 minutes',
   false, 1, 1001, 2001, NULL,
   'FULL', '{"model": "gpt-4o", "messages": [{"role": "user", "content": "Which one is the oldest question?"}]}'::jsonb),
  (9051, 'req-scan-051', 3001, 5001, 6001, 'success',
   NOW() - INTERVAL '6 minutes', NOW() - INTERVAL '5 minutes',
   NOW() - INTERVAL '5 minutes 30 seconds', NOW() - INTERVAL '4 minutes',
   false, 1, 1001, 2001, NULL,
   'FULL', '{"model": "gpt-4o", "messages": [{"role": "user", "content": "Which one is the middle question?"}]}'::jsonb),
  (9052, 'req-scan-052', 3001, 5001, 6001, 'success',
   NOW() - INTERVAL '3 minutes', NOW() - INTERVAL '2 minutes',
   NOW() - INTERVAL '2 minutes 30 seconds', NOW() - INTERVAL '1 minute',
   false, 1, 1001, 2001, NULL,
   'FULL', '{"model": "gpt-4o", "messages": [{"role": "user", "content": "Which one is the newest question?"}]}'::jsonb);
