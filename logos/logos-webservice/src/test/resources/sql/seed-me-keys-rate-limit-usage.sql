-- Rate-limit usage fixture (issue #672), layered on top of seed-me-keys.sql.
--
-- Requests count when the limiter charges the RPM slot: admission, i.e.
-- timestamp_forwarding. Tokens count when the limiter's record_tokens runs:
-- completion, i.e. timestamp_response. The rows below pin both edges.
--
-- traffic of alice's key 3101 that must count:
--   9301/9302: plain in-window cloud requests (total_tokens 1000 + 1500)
--   9303:      in-window local request (700)
--   9307:      arrived 70s ago, admitted only 10s ago after queue wait —
--              counted in the current window (cutting the request window on
--              timestamp_request would miss it). Explicit TRUE: admitted.
--   9310:      admitted 120s ago, completed 20s ago — long generation that
--              crossed the window edge: its 400 tokens completed inside the
--              window (the limiter's TPM window holds them), its request
--              admission did not (the RPM window no longer holds it)
--   9311:      admitted 30s ago, still in flight (no timestamp_response,
--              no result_status, no usage rows) — counts its request, no
--              tokens yet, exactly like the limiter
--   9313/9314/9315: pin the limiter's per-request token fallback
--              (total_tokens or prompt_tokens + completion_tokens, Python
--              `or`): 9313 has only the parts (300 + 200 -> 500), 9314 has a
--              zero total plus parts (0 + 100 + 150 -> 250), 9315 has a
--              non-zero total that does NOT equal the parts (90 vs 40 + 30 ->
--              90: the total wins, the parts are not added)
--   9316:      local counterpart of the parts-only case (120 + 130 -> 250)
--   9301-9316 carry rate_limit_admitted NULL except where noted: no limit
--              configured for that key/provider class (the orchestrator
--              never checked them) — still counted, like before the
--              admission column existed.
-- traffic that must NOT count:
--   9304: outside both windows (5 minutes old)
--   9305: still queued, no provider resolved, no timestamps at all
--   9306: inside the windows but bob's key 3102, not alice's
--   9308/9309: rejected by the limiter (rate_limit_admitted = FALSE). Their
--              timestamp_forwarding was written at scheduling, before
--              check_and_record rejected them, so they satisfy the
--              admission-window predicate and only the FALSE filter excludes
--              them. The 429 path never completes the request: no
--              timestamp_response, no result_status — and the usage rows
--              below cannot exist in production either (no completion, no
--              record_tokens); they are kept to prove the exclusion does not
--              depend on the timestamps.

INSERT INTO providers (id, name, base_url, provider_type, cloud_provider_type,
                       privacy_level, auth_name, auth_format)
VALUES (6102, 'test-cloud-provider', 'http://localhost', 'cloud', 'azure',
        'CLOUD_IN_EU_BY_US_PROVIDER', 'Authorization', 'Bearer {}');

INSERT INTO token_types (id, name) VALUES
  (91003, 'total_tokens'),
  (91004, 'prompt_tokens'),
  (91005, 'completion_tokens')
ON CONFLICT DO NOTHING;

INSERT INTO log_entry (id, request_id, api_key_id, model_id, provider_id, result_status,
                       timestamp_request, timestamp_forwarding, timestamp_response,
                       was_cold_start, queue_depth_at_enqueue, user_id, team_id, environment,
                       rate_limit_admitted)
VALUES
  (9301, 'req-rl-1', 3101, 5101, 6102, 'success',
   NOW() - INTERVAL '20 seconds', NOW() - INTERVAL '19 seconds', NOW() - INTERVAL '18 seconds',
   false, 0, 1101, 2101, NULL,
   NULL),
  (9302, 'req-rl-2', 3101, 5101, 6102, 'success',
   NOW() - INTERVAL '30 seconds', NOW() - INTERVAL '29 seconds', NOW() - INTERVAL '28 seconds',
   false, 0, 1101, 2101, NULL,
   NULL),
  (9303, 'req-rl-3', 3101, 5101, 6101, 'success',
   NOW() - INTERVAL '40 seconds', NOW() - INTERVAL '39 seconds', NOW() - INTERVAL '38 seconds',
   false, 0, 1101, 2101, NULL,
   NULL),
  (9304, 'req-rl-4', 3101, 5101, 6102, 'success',
   NOW() - INTERVAL '5 minutes', NOW() - INTERVAL '4 minutes', NOW() - INTERVAL '3 minutes',
   false, 0, 1101, 2101, NULL,
   NULL),
  (9305, 'req-rl-5', 3101, NULL, NULL, NULL,
   NOW() - INTERVAL '10 seconds', NULL, NULL,
   false, 0, 1101, 2101, NULL,
   NULL),
  (9306, 'req-rl-6', 3102, 5101, 6102, 'success',
   NOW() - INTERVAL '15 seconds', NOW() - INTERVAL '14 seconds', NOW() - INTERVAL '13 seconds',
   false, 0, 1102, 2101, NULL,
   NULL),
  (9307, 'req-rl-7', 3101, 5101, 6102, 'success',
   NOW() - INTERVAL '70 seconds', NOW() - INTERVAL '10 seconds', NOW() - INTERVAL '8 seconds',
   false, 6, 1101, 2101, NULL,
   TRUE),
  (9308, 'req-rl-8', 3101, 5101, 6102, NULL,
   NOW() - INTERVAL '12 seconds', NOW() - INTERVAL '11 seconds', NULL,
   false, 0, 1101, 2101, NULL,
   FALSE),
  (9309, 'req-rl-9', 3101, 5101, 6101, NULL,
   NOW() - INTERVAL '25 seconds', NOW() - INTERVAL '24 seconds', NULL,
   false, 0, 1101, 2101, NULL,
   FALSE),
  (9310, 'req-rl-10', 3101, 5101, 6102, 'success',
   NOW() - INTERVAL '125 seconds', NOW() - INTERVAL '120 seconds', NOW() - INTERVAL '20 seconds',
   false, 2, 1101, 2101, NULL,
   TRUE),
  (9311, 'req-rl-11', 3101, 5101, 6102, NULL,
   NOW() - INTERVAL '35 seconds', NOW() - INTERVAL '30 seconds', NULL,
   false, 0, 1101, 2101, NULL,
   TRUE),
  (9313, 'req-rl-13', 3101, 5101, 6102, 'success',
   NOW() - INTERVAL '26 seconds', NOW() - INTERVAL '25 seconds', NOW() - INTERVAL '24 seconds',
   false, 0, 1101, 2101, NULL,
   NULL),
  (9314, 'req-rl-14', 3101, 5101, 6102, 'success',
   NOW() - INTERVAL '33 seconds', NOW() - INTERVAL '32 seconds', NOW() - INTERVAL '31 seconds',
   false, 0, 1101, 2101, NULL,
   NULL),
  (9315, 'req-rl-15', 3101, 5101, 6102, 'success',
   NOW() - INTERVAL '37 seconds', NOW() - INTERVAL '36 seconds', NOW() - INTERVAL '35 seconds',
   false, 0, 1101, 2101, NULL,
   NULL),
  (9316, 'req-rl-16', 3101, 5101, 6101, 'success',
   NOW() - INTERVAL '46 seconds', NOW() - INTERVAL '45 seconds', NOW() - INTERVAL '44 seconds',
   false, 0, 1101, 2101, NULL,
   NULL);

INSERT INTO usage_tokens (type_id, log_entry_id, token_count)
VALUES
  ((SELECT id FROM token_types WHERE name = 'total_tokens'), 9301, 1000),
  ((SELECT id FROM token_types WHERE name = 'total_tokens'), 9302, 1500),
  ((SELECT id FROM token_types WHERE name = 'total_tokens'), 9303, 700),
  ((SELECT id FROM token_types WHERE name = 'total_tokens'), 9304, 9999),
  ((SELECT id FROM token_types WHERE name = 'total_tokens'), 9306, 4242),
  ((SELECT id FROM token_types WHERE name = 'total_tokens'), 9307, 100),
  ((SELECT id FROM token_types WHERE name = 'total_tokens'), 9308, 500),
  ((SELECT id FROM token_types WHERE name = 'total_tokens'), 9309, 300),
  ((SELECT id FROM token_types WHERE name = 'total_tokens'), 9310, 400),
  -- parts only: 300 + 200 -> 500
  ((SELECT id FROM token_types WHERE name = 'prompt_tokens'), 9313, 300),
  ((SELECT id FROM token_types WHERE name = 'completion_tokens'), 9313, 200),
  -- zero total falls through to the parts: 0 + 100 + 150 -> 250
  ((SELECT id FROM token_types WHERE name = 'total_tokens'), 9314, 0),
  ((SELECT id FROM token_types WHERE name = 'prompt_tokens'), 9314, 100),
  ((SELECT id FROM token_types WHERE name = 'completion_tokens'), 9314, 150),
  -- non-zero total wins over the parts: 90 (not 70)
  ((SELECT id FROM token_types WHERE name = 'total_tokens'), 9315, 90),
  ((SELECT id FROM token_types WHERE name = 'prompt_tokens'), 9315, 40),
  ((SELECT id FROM token_types WHERE name = 'completion_tokens'), 9315, 30),
  -- local parts only: 120 + 130 -> 250
  ((SELECT id FROM token_types WHERE name = 'prompt_tokens'), 9316, 120),
  ((SELECT id FROM token_types WHERE name = 'completion_tokens'), 9316, 130);
