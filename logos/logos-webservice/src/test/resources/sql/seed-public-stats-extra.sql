-- Extras for the public stats regression cases; load next to
-- seed-public-stats.sql (team 2001 published, team 2002 private).

-- A success requested just before the 7-day boundary but forwarded and
-- answered inside it. Every figure must agree on whether it counts: the
-- headline and the usage figures both range on the request timestamp.
INSERT INTO log_entry (id, request_id, api_key_id, model_id, provider_id, result_status,
                       timestamp_request, timestamp_forwarding, time_at_first_token, timestamp_response,
                       was_cold_start, queue_depth_at_enqueue, user_id, team_id, environment)
VALUES
  (9111, 'ps-boundary-late', 3001, 5001, 6001, 'success',
   NOW() - INTERVAL '7 days' - INTERVAL '1 minute', NOW() - INTERVAL '7 days' + INTERVAL '1 minute',
   NOW() - INTERVAL '7 days' + INTERVAL '90 seconds', NOW() - INTERVAL '7 days' + INTERVAL '2 minutes',
   false, 1, 1001, 2001, NULL);

INSERT INTO usage_tokens (type_id, log_entry_id, token_count)
SELECT tt.id, 9111, 11
FROM (SELECT id FROM token_types WHERE name = 'total_tokens' ORDER BY id LIMIT 1) tt;

-- Logos Agent sessions. Only sessions of an opted-in team's repository are
-- public; an automation identity counts as a session, never as a person.
INSERT INTO agent_workspaces (id, name, base_branch, volume_name, created_by, ephemeral)
VALUES (9801, 'ps-ws', 'main', 'ps-vol', 'test', FALSE);

INSERT INTO team_repositories (id, team_id, repo_url, repo_slug)
VALUES (9811, 2001, 'https://github.com/acme/public-one.git', 'acme/public-one'),
       (9812, 2002, 'https://github.com/acme/private-one.git', 'acme/private-one');

INSERT INTO agent_sessions (id, workspace_id, task, status, created_by, created_at,
                            open_pull_request, deploy_to_dev, screenshot_paths, no_push,
                            team_repository_id, pr_url)
VALUES
  -- human starter on the published team, inside every window
  (9821, 9801, 't', 'succeeded', 'alice', NOW() - INTERVAL '1 hour',
   TRUE, FALSE, '[]'::jsonb, FALSE, 9811, 'https://github.com/acme/public-one/pull/1'),
  -- GitHub trigger identity on the published team: a session, not a person
  (9822, 9801, 't', 'failed', 'logos-agent (trigger)', NOW() - INTERVAL '2 hours',
   TRUE, FALSE, '[]'::jsonb, FALSE, 9811, NULL),
  -- the runner's own re-queued attempt on the published team: a session,
  -- not a person
  (9826, 9801, 't', 'failed', 'the runner', NOW() - INTERVAL '5 hours',
   TRUE, FALSE, '[]'::jsonb, FALSE, 9811, NULL),
  -- workflow-analysis session on the published team, under the team's own
  -- automation identity: a session, not a person
  (9827, 9801, 't', 'failed', 'team-2001', NOW() - INTERVAL '6 hours',
   TRUE, FALSE, '[]'::jsonb, FALSE, 9811, NULL),
  -- private team: must not show up anywhere
  (9823, 9801, 't', 'succeeded', 'bob', NOW() - INTERVAL '3 hours',
   TRUE, FALSE, '[]'::jsonb, FALSE, 9812, 'https://github.com/acme/private-one/pull/2'),
  -- no repository, so no team to publish it under
  (9824, 9801, 't', 'succeeded', 'carol', NOW() - INTERVAL '4 hours',
   TRUE, FALSE, '[]'::jsonb, FALSE, NULL, NULL),
  -- an hour older than the 7-day window start, on the published team
  (9825, 9801, 't', 'succeeded', 'alice', NOW() - INTERVAL '7 days' - INTERVAL '1 hour',
   TRUE, FALSE, '[]'::jsonb, FALSE, 9811, NULL);
