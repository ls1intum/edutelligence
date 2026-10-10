-- Regression case for the key-type and lane split aggregates. A success on
-- the published team whose API key and provider were deleted after it was
-- logged: both ids are NULL, the ON DELETE SET NULL outcome. An inner join
-- on the key or the provider would drop the row from a split while the
-- headline total keeps counting it, so the split would no longer sum to the
-- headline.
UPDATE teams SET show_on_public_stats = TRUE WHERE id = 2001;

INSERT INTO log_entry (id, request_id, api_key_id, model_id, provider_id, result_status,
                       timestamp_request, timestamp_forwarding, time_at_first_token, timestamp_response,
                       was_cold_start, queue_depth_at_enqueue, user_id, team_id, environment)
VALUES
  (9108, 'ps-orphan', NULL, 5001, NULL, 'success',
   NOW() - INTERVAL '4 minutes', NOW() - INTERVAL '3 minutes',
   NOW() - INTERVAL '3 minutes 30 seconds', NOW() - INTERVAL '2 minutes',
   false, 0, NULL, 2001, NULL);
