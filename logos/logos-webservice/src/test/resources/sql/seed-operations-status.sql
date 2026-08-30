-- Lifecycle fixtures for the request feed's state filter, loaded by the status
-- filter test only (method-level) so the shared seed keeps its two rows.
-- One row per bucket:
--   queued   -> enqueued, never scheduled          (req-state-queued)
--   running  -> scheduled, not yet answered         (req-state-running)
--   error    -> answered with a failure             (req-state-error)
--   finished -> answered successfully               (req-state-finished)
-- They are the newest rows in the range, so each bucket is non-empty whichever
-- one the filter asks for. The ids keep clear of the shared seed (9001+).
INSERT INTO log_entry (id, request_id, api_key_id, model_id, provider_id, result_status,
                       timestamp_request, timestamp_forwarding, timestamp_response,
                       was_cold_start, queue_depth_at_enqueue, user_id, team_id, environment)
VALUES
  (9010, 'req-state-queued', 3001, 5001, 6001, NULL,
   NOW() - INTERVAL '60 seconds', NULL, NULL,
   false, 0, NULL, NULL, NULL),
  (9011, 'req-state-running', 3001, 5001, 6001, NULL,
   NOW() - INTERVAL '50 seconds', NOW() - INTERVAL '45 seconds', NULL,
   false, 0, NULL, NULL, NULL),
  (9012, 'req-state-error', 3001, 5001, 6001, 'error',
   NOW() - INTERVAL '40 seconds', NOW() - INTERVAL '35 seconds', NOW() - INTERVAL '30 seconds',
   false, 0, NULL, NULL, NULL),
  (9013, 'req-state-finished', 3001, 5001, 6001, 'success',
   NOW() - INTERVAL '20 seconds', NOW() - INTERVAL '15 seconds', NOW() - INTERVAL '10 seconds',
   true, 0, NULL, NULL, NULL);
