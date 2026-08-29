-- Rate-limit usage fixture (issue #672), layered on top of seed-me-keys.sql.
--
-- traffic inside the 60s window for alice's key 3101:
--   2 cloud requests (providers.provider_type = 'cloud') with 1000 + 1500 tokens
--   1 local request  (providers.provider_type = 'logosnode') with 700 tokens
-- traffic that must NOT be counted:
--   9304: outside the window (5 minutes old)
--   9305: still queued, no provider resolved yet
--   9306: inside the window but bob's key 3102, not alice's
INSERT INTO providers (id, name, base_url, provider_type, cloud_provider_type,
                       privacy_level, auth_name, auth_format)
VALUES (6102, 'test-cloud-provider', 'http://localhost', 'cloud', 'azure',
        'CLOUD_IN_EU_BY_US_PROVIDER', 'Authorization', 'Bearer {}');

INSERT INTO token_types (id, name) VALUES (91003, 'total_tokens') ON CONFLICT DO NOTHING;

INSERT INTO log_entry (id, request_id, api_key_id, model_id, provider_id, result_status,
                       timestamp_request, timestamp_forwarding, timestamp_response,
                       was_cold_start, queue_depth_at_enqueue, user_id, team_id, environment)
VALUES
  (9301, 'req-rl-1', 3101, 5101, 6102, 'success',
   NOW() - INTERVAL '20 seconds', NOW() - INTERVAL '19 seconds', NOW() - INTERVAL '18 seconds',
   false, 0, 1101, 2101, NULL),
  (9302, 'req-rl-2', 3101, 5101, 6102, 'success',
   NOW() - INTERVAL '30 seconds', NOW() - INTERVAL '29 seconds', NOW() - INTERVAL '28 seconds',
   false, 0, 1101, 2101, NULL),
  (9303, 'req-rl-3', 3101, 5101, 6101, 'success',
   NOW() - INTERVAL '40 seconds', NOW() - INTERVAL '39 seconds', NOW() - INTERVAL '38 seconds',
   false, 0, 1101, 2101, NULL),
  (9304, 'req-rl-4', 3101, 5101, 6102, 'success',
   NOW() - INTERVAL '5 minutes', NOW() - INTERVAL '4 minutes', NOW() - INTERVAL '3 minutes',
   false, 0, 1101, 2101, NULL),
  (9305, 'req-rl-5', 3101, NULL, NULL, NULL,
   NOW() - INTERVAL '10 seconds', NULL, NULL,
   false, 0, 1101, 2101, NULL),
  (9306, 'req-rl-6', 3102, 5101, 6102, 'success',
   NOW() - INTERVAL '15 seconds', NOW() - INTERVAL '14 seconds', NOW() - INTERVAL '13 seconds',
   false, 0, 1102, 2101, NULL);

INSERT INTO usage_tokens (type_id, log_entry_id, token_count)
VALUES
  ((SELECT id FROM token_types WHERE name = 'total_tokens'), 9301, 1000),
  ((SELECT id FROM token_types WHERE name = 'total_tokens'), 9302, 1500),
  ((SELECT id FROM token_types WHERE name = 'total_tokens'), 9303, 700),
  ((SELECT id FROM token_types WHERE name = 'total_tokens'), 9304, 9999),
  ((SELECT id FROM token_types WHERE name = 'total_tokens'), 9306, 4242);
