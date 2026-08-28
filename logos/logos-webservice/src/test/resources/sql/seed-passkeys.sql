INSERT INTO users (id, username, prename, name, role, email, keycloak_id, last_synced_at)
VALUES (1201, 'alice', 'Alice', 'Dev', 'app_developer', 'alice-passkey@test.com',
        '00000000-0000-0000-0000-000000001201', NOW());

INSERT INTO users (id, username, prename, name, role, email, keycloak_id, last_synced_at)
VALUES (1202, 'bob', 'Bob', 'Dev', 'app_developer', 'bob-passkey@test.com',
        '00000000-0000-0000-0000-000000001202', NOW());

INSERT INTO user_passkeys (id, user_id, credential_id, public_key, sign_count, label, created_at)
VALUES (12101, 1201, 'cGFzc2tleS1hbGljZS0x', '\x01', 0, 'Mac - Chrome', NOW() - INTERVAL '2 days');

INSERT INTO user_passkeys (id, user_id, credential_id, public_key, sign_count, label, created_at)
VALUES (12102, 1201, 'cGFzc2tleS1hbGljZS0y', '\x02', 0, 'iPhone - Safari', NOW() - INTERVAL '1 day');

INSERT INTO user_passkeys (id, user_id, credential_id, public_key, label, created_at)
VALUES (12103, 1202, 'cGFzc2tleS1ib2ItMQ', '\x03', 'Windows - Edge', NOW());
