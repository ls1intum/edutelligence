DELETE FROM team_provider_permissions WHERE team_id = 2101;
DELETE FROM team_model_permissions WHERE team_id = 2101;
DELETE FROM model_provider WHERE id = 7101;
DELETE FROM providers WHERE id = 6101;
DELETE FROM models WHERE id = 5101;
DELETE FROM api_keys WHERE id IN (3101, 3102, 3103);
DELETE FROM team_members WHERE team_id = 2101;
DELETE FROM teams WHERE id = 2101;
DELETE FROM users WHERE id IN (1101, 1102);
