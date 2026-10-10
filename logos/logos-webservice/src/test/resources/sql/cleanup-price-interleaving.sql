DELETE FROM usage_tokens WHERE log_entry_id IN (90101, 90102);
DELETE FROM log_entry WHERE id IN (90101, 90102);
DELETE FROM token_prices WHERE id IN (92105, 92106);
DELETE FROM token_types WHERE id = 9103;
DELETE FROM api_keys WHERE id = 5301;
DELETE FROM teams WHERE id = 2003;
