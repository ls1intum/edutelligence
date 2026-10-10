DELETE FROM agent_sessions WHERE id IN (9821, 9822, 9823, 9824, 9825, 9826);
DELETE FROM team_repositories WHERE id IN (9811, 9812);
DELETE FROM agent_workspaces WHERE id = 9801;
DELETE FROM usage_tokens WHERE log_entry_id = 9111;
DELETE FROM log_entry WHERE id = 9111;
