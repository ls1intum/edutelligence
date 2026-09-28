DELETE FROM usage_tokens WHERE id IN (9411, 9412, 9413, 9414, 9415, 9416, 9417);
DELETE FROM log_entry WHERE id IN (9401, 9402, 9403, 9404, 9405, 9406, 9407);
DELETE FROM token_types WHERE id IN (91401);
DELETE FROM providers WHERE id IN (6401);
-- The rollup still holds the rows deleted above until a pass recomputes their
-- hours. Left populated it would leak this test's traffic into the next one.
DELETE FROM log_entry_hourly_stats;
UPDATE log_entry_rollup_state SET processed_through = now();
