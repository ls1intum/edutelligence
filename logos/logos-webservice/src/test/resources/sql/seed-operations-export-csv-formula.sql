-- One row whose error message is itself a spreadsheet formula: the download
-- opens in Excel or LibreOffice, so the export must not hand it back as
-- something to evaluate — the cell goes out with the text marker in front.
INSERT INTO log_entry (id, request_id, api_key_id, model_id, provider_id, result_status,
                       timestamp_request, timestamp_forwarding, timestamp_response,
                       privacy_level, error_message, user_id, team_id)
VALUES
  (9046, 'req-csv-046', 3001, 5001, 6001, 'error',
   NOW() - INTERVAL '1 minute', NOW() - INTERVAL '30 seconds', NOW() - INTERVAL '20 seconds',
   'BILLING', '=SUM(A1:A5)', 1001, 2001);
