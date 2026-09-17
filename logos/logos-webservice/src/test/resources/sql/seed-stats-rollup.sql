-- Traffic for the statistics rollup tests.
--
-- Deliberately spread across *completed* hours as well as the running one:
-- log_entry_hourly_stats only ever holds whole hours, so rows in the current
-- hour are exactly what the live tail has to contribute. A seed that sat
-- entirely inside one hour would leave one of the two branches untested.
--
-- Mixed on purpose: a cloud and a local provider (the cloud/local split is
-- derived by joining providers at read time in both branches), a success and an
-- error, a cold and a warm start, rows with and without a user/team, and one row
-- with no timestamp_forwarding so the COALESCE in the effective-timestamp
-- expression is actually exercised on both sides.

-- Put the rollup into a known state before any of this exists. Liquibase builds
-- it at container start and nothing else in the suite refreshes it, but a
-- materialized view keeps whatever it was last built from - including rows a
-- previous test has since deleted. Rebuilding here, while log_entry is empty,
-- means the rollup provably holds none of the traffic below, which is what lets
-- the tests read a "before the refresh" baseline.
REFRESH MATERIALIZED VIEW log_entry_hourly_stats;

-- A cloud counterpart to seed-configuration's LOCAL provider 6001.
INSERT INTO providers (id, name, base_url, provider_type, privacy_level, auth_name, auth_format)
VALUES (6401, 'rollup-cloud-provider', 'https://api.example.com', 'cloud',
        'CLOUD_NOT_IN_EU_BY_US_PROVIDER', 'Authorization', 'Bearer {}');

INSERT INTO token_types (id, name) VALUES (91401, 'total_tokens') ON CONFLICT DO NOTHING;

INSERT INTO log_entry (id, request_id, api_key_id, model_id, provider_id, result_status,
                       timestamp_request, timestamp_forwarding, timestamp_response,
                       was_cold_start, error_message, user_id, team_id)
VALUES
  -- ── Completed hours: these end up in the rollup ──────────────────────────
  (9401, 'roll-001', 3001, 5001, 6001, 'success',
   date_trunc('hour', NOW()) - INTERVAL '13 hours',
   date_trunc('hour', NOW()) - INTERVAL '13 hours' + INTERVAL '2 seconds',
   date_trunc('hour', NOW()) - INTERVAL '13 hours' + INTERVAL '12 seconds',
   false, NULL, 1001, 2001),
  (9402, 'roll-002', 3001, 5001, 6001, 'success',
   date_trunc('hour', NOW()) - INTERVAL '13 hours' + INTERVAL '30 minutes',
   date_trunc('hour', NOW()) - INTERVAL '13 hours' + INTERVAL '30 minutes 1 second',
   date_trunc('hour', NOW()) - INTERVAL '13 hours' + INTERVAL '30 minutes 20 seconds',
   true, NULL, 1001, 2001),
  (9403, 'roll-003', 3001, 5001, 6401, 'error',
   date_trunc('hour', NOW()) - INTERVAL '11 hours',
   date_trunc('hour', NOW()) - INTERVAL '11 hours' + INTERVAL '1 second',
   date_trunc('hour', NOW()) - INTERVAL '11 hours' + INTERVAL '4 seconds',
   false, 'upstream exploded', NULL, NULL),
  -- No timestamp_forwarding: the effective timestamp falls back to
  -- timestamp_request, in the rollup and in the live tail alike.
  (9404, 'roll-004', 3001, 5001, 6001, 'success',
   date_trunc('hour', NOW()) - INTERVAL '10 hours' + INTERVAL '15 minutes',
   NULL,
   date_trunc('hour', NOW()) - INTERVAL '10 hours' + INTERVAL '15 minutes 5 seconds',
   false, NULL, 1001, 2001),

  -- ── Running hour: only the live tail can contribute these ────────────────
  (9405, 'roll-005', 3001, 5001, 6401, 'success',
   date_trunc('hour', NOW()) + INTERVAL '1 minute',
   date_trunc('hour', NOW()) + INTERVAL '1 minute 1 second',
   date_trunc('hour', NOW()) + INTERVAL '1 minute 9 seconds',
   false, NULL, 1001, 2001),
  (9406, 'roll-006', 3001, 5001, 6001, 'error',
   date_trunc('hour', NOW()) + INTERVAL '2 minutes',
   date_trunc('hour', NOW()) + INTERVAL '2 minutes 1 second',
   date_trunc('hour', NOW()) + INTERVAL '2 minutes 3 seconds',
   true, 'timed out', NULL, NULL);

-- Inside the six-hour lag: its hour is closed, but the rollup deliberately
-- stops short of it because a row this recent can still be written to.
INSERT INTO log_entry (id, request_id, api_key_id, model_id, provider_id, result_status,
                       timestamp_request, timestamp_forwarding, timestamp_response,
                       was_cold_start, error_message, user_id, team_id)
VALUES
  (9407, 'roll-007', 3001, 5001, 6001, 'success',
   date_trunc('hour', NOW()) - INTERVAL '2 hours',
   date_trunc('hour', NOW()) - INTERVAL '2 hours' + INTERVAL '1 second',
   date_trunc('hour', NOW()) - INTERVAL '2 hours' + INTERVAL '7 seconds',
   false, NULL, 1001, 2001);

-- Token counts on both sides of the watermark, so the totals card's token sum is
-- covered by the rollup column and by the live LATERAL that mirrors it.
INSERT INTO usage_tokens (id, log_entry_id, type_id, token_count)
VALUES
  (9411, 9401, 91401, 100),
  (9412, 9402, 91401, 200),
  (9413, 9403, 91401, 300),
  (9414, 9404, 91401, 400),
  (9415, 9405, 91401, 500),
  (9416, 9406, 91401, 600),
  (9417, 9407, 91401, 700);
