DELETE FROM api_keys
WHERE id IN (3001, 3002, 3003, 3004)
   OR user_id IN (
        SELECT id FROM users
        WHERE id IN (1001, 1002, 1003)
           OR keycloak_id IN (
                '00000000-0000-0000-0000-000000001001',
                '00000000-0000-0000-0000-000000001002',
                '00000000-0000-0000-0000-000000001003',
                '33333333-3333-3333-3333-333333333333',
                '44444444-4444-4444-4444-444444444444'
           )
           OR lower(email) IN ('legacy-admin@test.com', 'fresh@tum.de', 'newbie@tum.de')
   );
DELETE FROM team_members
WHERE team_id = 2001
   OR user_id IN (
        SELECT id FROM users
        WHERE id IN (1001, 1002, 1003)
           OR keycloak_id IN (
                '00000000-0000-0000-0000-000000001001',
                '00000000-0000-0000-0000-000000001002',
                '00000000-0000-0000-0000-000000001003',
                '33333333-3333-3333-3333-333333333333',
                '44444444-4444-4444-4444-444444444444'
           )
           OR lower(email) IN ('legacy-admin@test.com', 'fresh@tum.de', 'newbie@tum.de')
   );
DELETE FROM teams WHERE id = 2001;
DELETE FROM users
WHERE id IN (1001, 1002, 1003)
   OR keycloak_id IN (
        '00000000-0000-0000-0000-000000001001',
        '00000000-0000-0000-0000-000000001002',
        '00000000-0000-0000-0000-000000001003',
        '33333333-3333-3333-3333-333333333333',
        '44444444-4444-4444-4444-444444444444'
   )
   OR lower(email) IN ('legacy-admin@test.com', 'fresh@tum.de', 'newbie@tum.de');
