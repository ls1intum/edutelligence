-- Notification fixtures exercising each fan-out kind (role / team / user).
-- Depends on seed-identity.sql for users 1001..1003 and team 2001 — run that
-- first. These tables belong solely to the notification feature, so the seed
-- (and cleanup) wipe them wholesale for a known-good starting state.
DELETE FROM notification_reads;
DELETE FROM notification_recipients;
DELETE FROM notifications;

-- 9001: addressed to the whole app_admin role (visible to 1002 only).
INSERT INTO notifications (id, type, title, body, payload, source, actor_user_id, created_at)
VALUES (9001, 'budget_hit', 'Monthly budget hit', 'Team exceeded its budget',
        '{"team_id": 2001}'::jsonb, 'orchestrator', 1001, NOW());
INSERT INTO notification_recipients (notification_id, recipient_kind, recipient_id, recipient_role)
VALUES (9001, 'role', NULL, 'app_admin');

-- 9002: addressed to team 2001 (all its members see it: 1001, 1002, 1003).
INSERT INTO notifications (id, type, title, body, payload, source, actor_user_id, created_at)
VALUES (9002, 'new_models_available', 'New models for your team', NULL,
        '{"models": ["gpt-4o"]}'::jsonb, 'webservice', NULL, NOW());
INSERT INTO notification_recipients (notification_id, recipient_kind, recipient_id, recipient_role)
VALUES (9002, 'team', 2001, NULL);

-- 9003: addressed to a single user (1003).
INSERT INTO notifications (id, type, title, body, payload, source, actor_user_id, created_at)
VALUES (9003, 'deployment', 'Deployment finished', NULL, NULL, 'webservice', 1003, NOW());
INSERT INTO notification_recipients (notification_id, recipient_kind, recipient_id, recipient_role)
VALUES (9003, 'user', 1003, NULL);

-- 9004: addressed to the whole logos_admin role (visible to 1003 only).
INSERT INTO notifications (id, type, title, body, payload, source, actor_user_id, created_at)
VALUES (9004, 'benchmark_result_ready', 'Benchmarks ready for review', NULL,
        '{"benchmark_id": 42}'::jsonb, 'webservice', NULL, NOW());
INSERT INTO notification_recipients (notification_id, recipient_kind, recipient_id, recipient_role)
VALUES (9004, 'role', NULL, 'logos_admin');

-- Read state: adminuser (1002) has already read 9001.
INSERT INTO notification_reads (notification_id, user_id, read_at)
VALUES (9001, 1002, NOW());
