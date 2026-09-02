-- Export-only fixtures (issue #667), kept in their own file so the shared
-- operations seed stays untouched for the other test classes.

-- Consent-based (FULL) trace: the requester opted into full logging, so the
-- request and response data was stored and belongs in the export. The stored
-- headers are the request's headers, which means the authorization header
-- holds a working API key — exactly what the export must not hand back.
INSERT INTO log_entry (id, request_id, api_key_id, model_id, provider_id, result_status,
                       timestamp_request, timestamp_forwarding, timestamp_response,
                       privacy_level, client_ip, input_payload, headers, response_payload,
                       was_cold_start, queue_depth_at_enqueue, user_id, team_id, environment)
VALUES
  (9003, 'req-ccc-333', 3001, 5001, 6001, 'success',
   NOW() - INTERVAL '6 minutes', NOW() - INTERVAL '5 minutes', NOW() - INTERVAL '4 minutes',
   'FULL', '127.0.0.1',
   '{"model": "gpt-4", "messages": [{"role": "user", "content": "Hello, Logos"}]}'::jsonb,
   '{"content-type": "application/json", "authorization": "Bearer lg-9c4e5f6a7b8c9d0e1f2a3b4c5d6e7f80"}'::jsonb,
   '{"choices": [{"message": {"role": "assistant", "content": "Hi there!"}}]}'::jsonb,
   false, 1, 1001, 2001, NULL);

-- Billing-only row in the same team and window: no content was stored for it,
-- but it is still part of the export — with the content columns empty.
INSERT INTO log_entry (id, request_id, api_key_id, model_id, provider_id, result_status,
                       timestamp_request, timestamp_forwarding, timestamp_response,
                       privacy_level, user_id, team_id)
VALUES
  (9004, 'req-ddd-444', 3001, 5001, 6001, 'success',
   NOW() - INTERVAL '3 minutes', NOW() - INTERVAL '2 minutes', NOW() - INTERVAL '1 minute',
   'BILLING', 1001, 2001);

-- A second key of team 2001, opted into full logging: the shared seed keys
-- are all at the BILLING default, and the view needs one team where
-- full_logging_enabled is true.
INSERT INTO api_keys (id, key_value, name, key_type, user_id, team_id, is_active, log)
VALUES (3009, 'full-key-9', 'full key', 'developer', 1001, 2001, true, 'FULL');
