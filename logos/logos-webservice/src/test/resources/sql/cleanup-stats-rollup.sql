DELETE FROM usage_tokens WHERE id IN (9411, 9412, 9413, 9414, 9415, 9416);
DELETE FROM log_entry WHERE id IN (9401, 9402, 9403, 9404, 9405, 9406);
DELETE FROM token_types WHERE id IN (91401);
DELETE FROM providers WHERE id IN (6401);
-- The rollup is a materialized view, so it still holds the rows deleted above
-- until it is rebuilt. Left populated it would leak this test's traffic into
-- the next one that refreshes.
REFRESH MATERIALIZED VIEW log_entry_hourly_stats;
