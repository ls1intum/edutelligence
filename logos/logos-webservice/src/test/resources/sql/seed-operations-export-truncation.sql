-- Enough rows for team 2001 to outrun the export's cap, which the test shrinks
-- to two. The two newest rows are billing-only on purpose: the export keeps
-- the newest slice, and the file's consent note is computed over that slice,
-- not the window — the FULL row 9042 sits just behind the cap, so the note
-- must say "no full logging in this window" even though full logging is
-- activated for the team (the added key 3009) and consented traffic exists a
-- row further down.
INSERT INTO log_entry (id, request_id, api_key_id, model_id, provider_id, result_status,
                       timestamp_request, timestamp_forwarding, timestamp_response,
                       privacy_level, input_payload, user_id, team_id)
VALUES
  (9040, 'req-trunc-040', 3001, 5001, 6001, 'success',
   NOW() - INTERVAL '1 minute', NOW() - INTERVAL '60 seconds', NOW() - INTERVAL '30 seconds',
   'BILLING', NULL, 1001, 2001),
  (9041, 'req-trunc-041', 3001, 5001, 6001, 'success',
   NOW() - INTERVAL '2 minutes', NOW() - INTERVAL '90 seconds', NOW() - INTERVAL '60 seconds',
   'BILLING', NULL, 1001, 2001),
  (9042, 'req-trunc-042', 3001, 5001, 6001, 'success',
   NOW() - INTERVAL '3 minutes', NOW() - INTERVAL '150 seconds', NOW() - INTERVAL '120 seconds',
   'FULL', '{"model": "gpt-4", "messages": [{"role": "user", "content": "Behind the cap"}]}'::jsonb, 1001, 2001),
  (9043, 'req-trunc-043', 3001, 5001, 6001, 'success',
   NOW() - INTERVAL '4 minutes', NOW() - INTERVAL '230 seconds', NOW() - INTERVAL '200 seconds',
   'BILLING', NULL, 1001, 2001),
  (9044, 'req-trunc-044', 3001, 5001, 6001, 'success',
   NOW() - INTERVAL '5 minutes', NOW() - INTERVAL '290 seconds', NOW() - INTERVAL '260 seconds',
   'BILLING', NULL, 1001, 2001);
