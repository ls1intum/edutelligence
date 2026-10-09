-- The public stats page counts settled successes on opted-in teams only, so
-- the fixtures mix successes with an error and a timeout that share the key,
-- team and provider of successful rows: any aggregate that counts a failing
-- row is wrong. Team 2001 is published; team 2002 stays private so its
-- traffic must not leak into any public figure.
UPDATE teams SET show_on_public_stats = TRUE, public_category = 'Research' WHERE id = 2001;

-- A rollup whose last pass is older than its staleness limit is not trusted,
-- so every usage figure below is read straight from log_entry. Otherwise the
-- hours before the migration would count as rolled up although this seed's
-- rows were never rolled up.
UPDATE log_entry_rollup_state SET processed_through = now() - INTERVAL '1 day';
UPDATE teams SET show_on_public_stats = FALSE WHERE id = 2002;

INSERT INTO providers (id, name, base_url, provider_type, privacy_level, auth_name, auth_format)
VALUES (9601, 'local-node', 'http://logos-orchestrator:8000', 'logosnode', 'LOCAL', 'Authorization', 'Bearer {}');

INSERT INTO log_entry (id, request_id, api_key_id, model_id, provider_id, result_status,
                       timestamp_request, timestamp_forwarding, time_at_first_token, timestamp_response,
                       was_cold_start, queue_depth_at_enqueue, user_id, team_id, environment)
VALUES
  -- three team-2001 successes on the member's developer key: two cloud, one local
  (9101, 'ps-team-cloud-1', 3001, 5001, 6001, 'success',
   NOW() - INTERVAL '10 minutes', NOW() - INTERVAL '9 minutes',
   NOW() - INTERVAL '9 minutes 30 seconds', NOW() - INTERVAL '8 minutes',
   false, 1, 1001, 2001, NULL),
  (9102, 'ps-team-local', 3001, 5001, 9601, 'success',
   NOW() - INTERVAL '9 minutes', NOW() - INTERVAL '8 minutes',
   NOW() - INTERVAL '8 minutes 30 seconds', NOW() - INTERVAL '7 minutes',
   false, 1, 1001, 2001, NULL),
  (9107, 'ps-team-cloud-2', 3001, 5001, 6001, 'success',
   NOW() - INTERVAL '8 minutes 30 seconds', NOW() - INTERVAL '8 minutes',
   NOW() - INTERVAL '7 minutes 45 seconds', NOW() - INTERVAL '7 minutes 30 seconds',
   false, 1, 1001, 2001, NULL),
  -- older than the default 30-day window: days=30 / days=7 must drop it,
  -- days=all (and days=90/365) must keep it
  (9110, 'ps-team-cloud-old', 3001, 5001, 6001, 'success',
   NOW() - INTERVAL '40 days', NOW() - INTERVAL '40 days' + INTERVAL '1 minute',
   NOW() - INTERVAL '40 days' + INTERVAL '90 seconds', NOW() - INTERVAL '40 days' + INTERVAL '2 minutes',
   false, 1, 1001, 2001, NULL),
  -- the two failures below sit next to the successes above: counting them
  -- would move team 2001, the developer split and both lanes
  (9103, 'ps-team-error', 3001, 5001, 6001, 'error',
   NOW() - INTERVAL '8 minutes', NOW() - INTERVAL '7 minutes',
   NULL, NOW() - INTERVAL '6 minutes',
   false, 1, 1001, 2001, NULL),
  (9104, 'ps-team-timeout', 3003, 5001, 9601, 'timeout',
   NOW() - INTERVAL '7 minutes', NOW() - INTERVAL '6 minutes',
   NULL, NOW() - INTERVAL '5 minutes',
   false, 1, 1002, 2001, NULL),
  -- application-key successes on the private team: must not appear until an
  -- admin opts team 2002 in
  (9105, 'ps-app-cloud-a', 3002, 5001, 6001, 'success',
   NOW() - INTERVAL '6 minutes', NOW() - INTERVAL '5 minutes',
   NOW() - INTERVAL '5 minutes 30 seconds', NOW() - INTERVAL '4 minutes',
   false, 0, NULL, 2002, 'production'),
  (9106, 'ps-app-cloud-b', 3002, 5001, 6001, 'success',
   NOW() - INTERVAL '5 minutes', NOW() - INTERVAL '4 minutes',
   NOW() - INTERVAL '4 minutes 30 seconds', NOW() - INTERVAL '3 minutes',
   false, 0, NULL, 2002, 'production');

-- Token counts: the error row carries far more tokens than all successes
-- together, so any token figure that counted it would be visibly wrong.
INSERT INTO token_types (id, name) VALUES (9701, 'total_tokens') ON CONFLICT DO NOTHING;
INSERT INTO usage_tokens (type_id, log_entry_id, token_count)
SELECT tt.id, v.log_entry_id, v.token_count
FROM (SELECT id FROM token_types WHERE name = 'total_tokens' ORDER BY id LIMIT 1) tt
CROSS JOIN (VALUES (9101, 100), (9102, 50), (9107, 30), (9110, 7), (9103, 1000), (9105, 20), (9106, 20))
     AS v(log_entry_id, token_count);
