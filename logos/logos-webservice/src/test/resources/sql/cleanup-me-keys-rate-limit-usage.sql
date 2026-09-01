-- Deleting the log rows cascades to their usage_tokens rows.
DELETE FROM log_entry WHERE id IN (9301, 9302, 9303, 9304, 9305, 9306, 9307, 9308, 9309,
                                   9310, 9311, 9313, 9314, 9315, 9316);
DELETE FROM providers WHERE id = 6102;
DELETE FROM token_types WHERE id IN (91003, 91004, 91005)
  AND name IN ('total_tokens', 'prompt_tokens', 'completion_tokens');
