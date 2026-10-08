DELETE FROM log_entry WHERE id IN (9101, 9102, 9103, 9104, 9105, 9106, 9107, 9110);
DELETE FROM providers WHERE id IN (9601);
UPDATE teams SET show_on_public_stats = FALSE WHERE id IN (2001, 2002);
