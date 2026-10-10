DELETE FROM usage_tokens WHERE log_entry_id IN (9101, 9102, 9103, 9104, 9105, 9106, 9107, 9110);
DELETE FROM log_entry WHERE id IN (9101, 9102, 9103, 9104, 9105, 9106, 9107, 9110);
DELETE FROM providers WHERE id IN (9601);
DELETE FROM token_types WHERE id = 9701;
UPDATE teams SET show_on_public_stats = FALSE, public_category = NULL WHERE id IN (2001, 2002);
DELETE FROM log_entry_hourly_stats WHERE team_id IN (2001, 2002);
DELETE FROM log_entry_rollup_dirty_hours;
UPDATE log_entry_rollup_state SET processed_through = now();
