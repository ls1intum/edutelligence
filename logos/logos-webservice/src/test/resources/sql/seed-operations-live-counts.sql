-- In-flight rows for team 2001 at both sides of the horizon. A row without a
-- response is only live while it could still be running: a request that
-- started beyond the in-flight horizon is stranded (a client or a worker died
-- mid-flight), and counting it as queued or running would count failures from
-- days ago on every poll. 9031 and 9032 are fresh and must count, 9030 and
-- 9033 are beyond the horizon and must not.
INSERT INTO log_entry (id, request_id, api_key_id, model_id, provider_id, result_status,
                       timestamp_request, timestamp_forwarding, timestamp_response,
                       was_cold_start, queue_depth_at_enqueue, user_id, team_id)
VALUES
  -- Stranded in the queue: requested 40 minutes ago, never forwarded, never
  -- answered.
  (9030, 'req-live-030', 3001, 5001, 6001, NULL,
   NOW() - INTERVAL '40 minutes', NULL, NULL,
   false, 1, 1001, 2001),
  -- Fresh in the queue: requested 5 minutes ago, not forwarded yet.
  (9031, 'req-live-031', 3001, 5001, 6001, NULL,
   NOW() - INTERVAL '5 minutes', NULL, NULL,
   false, 1, 1001, 2001),
  -- Fresh and running: forwarded 4 minutes ago, still no response.
  (9032, 'req-live-032', 3001, 5001, 6001, NULL,
   NOW() - INTERVAL '5 minutes', NOW() - INTERVAL '4 minutes', NULL,
   false, 1, 1001, 2001),
  -- Stranded mid-flight: forwarded 40 minutes ago, never answered.
  (9033, 'req-live-033', 3001, 5001, 6001, NULL,
   NOW() - INTERVAL '45 minutes', NOW() - INTERVAL '40 minutes', NULL,
   false, 1, 1001, 2001);
