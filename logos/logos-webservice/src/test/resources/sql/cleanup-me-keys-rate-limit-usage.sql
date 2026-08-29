-- Deleting the log rows cascades to their usage_tokens rows.
DELETE FROM log_entry WHERE id IN (9301, 9302, 9303, 9304, 9305, 9306, 9307);
DELETE FROM providers WHERE id = 6102;
DELETE FROM token_types WHERE id = 91003 AND name = 'total_tokens';
