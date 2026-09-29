-- One extra consented row for the CSV export test: its stored question text
-- carries a comma and double quotes, which is exactly what breaks a naive
-- CSV cell, so the download must come out quoted with the quotes doubled.
INSERT INTO log_entry (id, request_id, api_key_id, model_id, provider_id, result_status,
                       timestamp_request, timestamp_forwarding, timestamp_response,
                       privacy_level, input_payload, user_id, team_id)
VALUES
  (9045, 'req-csv-045', 3001, 5001, 6001, 'success',
   NOW() - INTERVAL '2 minutes', NOW() - INTERVAL '90 seconds', NOW() - INTERVAL '60 seconds',
   'FULL', '{"model": "gpt-4", "messages": [{"role": "user", "content": "Hello, \"Logos\" - are we done?"}]}'::jsonb, 1001, 2001);
